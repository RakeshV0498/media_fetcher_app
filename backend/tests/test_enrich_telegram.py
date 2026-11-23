import httpx
import pytest
import respx
from sqlalchemy import select

from app.config import settings
from app.download import service
from app.download.mock import MockClient
from app.models import Download, Release, Source, Tag, Variant
from app.notify import telegram
from app.parsing.enrich import enrich_pending, enrich_release, map_absolute

OP_COUNTS = [(0, 5), (1, 61), (2, 16), (3, 14)]


def test_map_absolute():
    assert map_absolute(OP_COUNTS, 1) == (1, 1)
    assert map_absolute(OP_COUNTS, 61) == (1, 61)
    assert map_absolute(OP_COUNTS, 62) == (2, 1)     # specials (season 0) ignored
    assert map_absolute(OP_COUNTS, 91) == (3, 14)
    assert map_absolute(OP_COUNTS, 92) is None
    assert map_absolute(OP_COUNTS, 0) is None


def _release(db, **kw):
    r = Release(release_key=kw.pop("key", "k"), **kw)
    db.add(r)
    db.commit()
    return r


@respx.mock
def test_enrich_tv_resolves_absolute_via_tmdb_and_caches(db):
    r = _release(db, title="One Piece", kind="tv", absolute_episode=70)
    s = respx.get("https://api.themoviedb.org/3/search/tv").mock(return_value=httpx.Response(200, json={
        "results": [{"id": 37854, "poster_path": "/p.jpg", "overview": "Pirates", "genre_ids": [16],
                     "original_language": "ja", "origin_country": ["JP"]}]}))
    respx.get("https://api.themoviedb.org/3/tv/37854").mock(return_value=httpx.Response(200, json={
        "seasons": [{"season_number": n, "episode_count": c} for n, c in OP_COUNTS]}))
    respx.post("https://graphql.anilist.co").mock(return_value=httpx.Response(200, json={"data": {"Media": {
        "id": 1, "coverImage": {"large": "http://c"}, "description": "d", "genres": ["Action"],
        "countryOfOrigin": "JP"}}}))
    with httpx.Client() as http:
        assert enrich_release(db, r, http, tmdb_key="k")
        assert (r.season, r.episode) == (2, 9)
        assert r.poster_url.endswith("/p.jpg") and "Action" in r.genres
        assert db.get(Tag, r.suggested_tag_id).name == "Anime"
        r2 = _release(db, key="k2", title="One Piece", kind="tv", absolute_episode=71)
        enrich_release(db, r2, http, tmdb_key="k")
    assert s.call_count == 1  # second episode served from cache
    assert (r2.season, r2.episode) == (2, 10)


@respx.mock
def test_enrich_movie_tag_from_language_and_no_key_is_harmless(db):
    r = _release(db, title="Some Film", kind="movie", year=2022)
    respx.get("https://api.themoviedb.org/3/search/movie").mock(return_value=httpx.Response(200, json={
        "results": [{"id": 1, "poster_path": None, "overview": "x", "genre_ids": [], "original_language": "ta"}]}))
    with httpx.Client() as http:
        assert enrich_release(db, r, http, tmdb_key="k")
        assert db.get(Tag, r.suggested_tag_id).name == "Tamil Movie"
        r2 = _release(db, key="m2", title="Other", kind="movie")
        assert enrich_release(db, r2, http, tmdb_key="") is False  # no key, movie: nothing to do
        assert r2.enriched_at is not None


@respx.mock
def test_enrich_failure_is_transient_and_not_cached(db):
    r = _release(db, title="Flaky", kind="movie")
    respx.get("https://api.themoviedb.org/3/search/movie").mock(return_value=httpx.Response(500))
    with httpx.Client() as http:
        assert enrich_release(db, r, http, tmdb_key="k") is False
    assert r.enriched_at is None  # retried by the next job run


@respx.mock
def test_enrich_pending_only_unenriched(db, monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "")
    _release(db, title="A", kind="movie")
    with httpx.Client() as http:
        enrich_pending(db, http)
        assert enrich_pending(db, http) == 0


# ---- Telegram ----
@pytest.fixture()
def tg(monkeypatch):
    monkeypatch.setattr(settings, "telegram_enabled", True)
    monkeypatch.setattr(settings, "telegram_bot_token", "T")
    monkeypatch.setattr(settings, "telegram_chat_id", "42")
    monkeypatch.setattr(service, "_client", MockClient())


def _with_variants(db):
    src = Source(name="s", url="u")
    db.add(src)
    db.flush()
    tag = db.scalar(select(Tag).where(Tag.name == "TV Show"))
    r = _release(db, title="Cool Show", kind="tv", season=1, episode=2, suggested_tag_id=tag.id)
    vs = [Variant(release_id=r.id, source_id=src.id, ident=str(i), quality=q, seeders=sd,
                  magnet=f"magnet:?xt=urn:btih:{i}") for i, (q, sd) in enumerate([("720p", 5), ("1080p", 50)])]
    db.add_all(vs)
    db.commit()
    return r, vs


@respx.mock
def test_notify_sends_once_with_ranked_buttons(db, tg):
    r, vs = _with_variants(db)
    route = respx.post("https://api.telegram.org/botT/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    with httpx.Client() as http:
        assert telegram.notify_new(db, http) == 1
        assert telegram.notify_new(db, http) == 0  # not re-sent
    body = route.calls[0].request.content.decode()
    assert f"a:{r.id}:{vs[1].id}" in body and body.index("1080p") < body.index("720p")  # best seeded first
    assert f"r:{r.id}" in body and '"chat_id":"42"' in body.replace(" ", "")


def test_notify_disabled_sends_nothing(db, monkeypatch):
    monkeypatch.setattr(settings, "telegram_enabled", False)
    _with_variants(db)
    with httpx.Client() as http:
        assert telegram.notify_new(db, http) == 0


def test_callbacks_authorized_only_and_respect_gate(db, tg, monkeypatch):
    r, vs = _with_variants(db)
    assert telegram.handle_callback(db, f"a:{r.id}:{vs[1].id}", 999) == "Not authorized"
    assert db.scalars(select(Download)).first() is None
    assert telegram.handle_callback(db, f"a:{r.id}:{vs[1].id}", 42) == "Approved"
    assert db.scalars(select(Download)).one().variant_id == vs[1].id
    assert telegram.handle_callback(db, f"a:{r.id}:{vs[1].id}", 42).startswith("Blocked")  # already approved


def test_callback_blocked_by_gate_and_reject(db, tg, monkeypatch):
    r, vs = _with_variants(db)

    class Real(MockClient):
        is_mock = False
    monkeypatch.setattr(service, "_client", Real())
    monkeypatch.setattr(settings, "downloads_enabled", False)
    assert "disabled" in telegram.handle_callback(db, f"a:{r.id}:{vs[0].id}", "42")
    assert r.status == "new"
    assert telegram.handle_callback(db, f"r:{r.id}", 42) == "Rejected"
    assert telegram.handle_callback(db, "zzz", 42) == "Unknown action"
