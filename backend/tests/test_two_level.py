import httpx
import pytest
import respx
from sqlalchemy import select

from app.models import Release, Source, Variant
from app.scanner.details import load_versions
from app.scanner.runner import scan_source

SEL = {
    "item": "div.entry", "title": "a.t", "link": "a.t@href",
    "detail": {"item": "div.ver", "title": ".name", "magnet": "a.mag@href", "size": ".sz", "seeders": ".se"},
}
LISTING = """<html><body>
<div class="entry"><a class="t" href="/m/1">Sample Film (2024) HD</a></div>
<div class="entry"><a class="t" href="/m/2">Another Film (2023) HD</a></div>
</body></html>"""
DETAIL = """<html><body>
<div class="ver"><span class="name">Sample Film (2024) 2160p x265</span><span class="sz">9.1 GB</span><span class="se">40</span>
 <a class="mag" href="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA">m</a></div>
<div class="ver"><span class="name">Sample Film (2024) 1080p x264</span><span class="sz">2.4 GB</span><span class="se">310</span>
 <a class="mag" href="magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB">m</a></div>
<div class="ver"><span class="name">Sample Film (2024) 720p x264</span><span class="sz">900 MB</span><span class="se">12</span>
 <a class="mag" href="magnet:?xt=urn:btih:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC">m</a></div>
</body></html>"""


@pytest.fixture()
def source(db):
    src = Source(name="two-level", url="https://films.example/list", mode="html", selectors=SEL)
    db.add(src)
    db.commit()
    return src


@respx.mock
def test_scan_records_detail_urls_without_creating_fake_variants(db, source):
    respx.get("https://films.example/list").mock(return_value=httpx.Response(200, text=LISTING))
    with httpx.Client() as c:
        status = scan_source(db, source, c, sleep=lambda _: None)
    assert status == "ok: 2 items, 2 new"
    rels = {r.title: r for r in db.scalars(select(Release))}
    assert rels["Sample Film"].detail_url == "https://films.example/m/1"       # relative link resolved
    assert rels["Sample Film"].detail_source_id == source.id
    assert db.scalars(select(Variant)).all() == []                              # nothing downloadable yet


@respx.mock
def test_load_versions_attaches_all_resolutions_and_is_idempotent(db, source):
    respx.get("https://films.example/list").mock(return_value=httpx.Response(200, text=LISTING))
    detail = respx.get("https://films.example/m/1").mock(return_value=httpx.Response(200, text=DETAIL))
    with httpx.Client() as c:
        scan_source(db, source, c, sleep=lambda _: None)
        rel = db.scalar(select(Release).where(Release.title == "Sample Film"))
        assert load_versions(db, rel, c) == 3
        assert load_versions(db, rel, c) == 0                                   # again: nothing duplicated
    assert detail.call_count == 2
    vs = sorted(rel.variants, key=lambda v: -(v.seeders or 0))
    assert [(v.quality, v.seeders) for v in vs] == [("1080p", 310), ("2160p", 40), ("720p", 12)]
    assert vs[0].size_bytes == 2_400_000_000 and vs[0].magnet.startswith("magnet:?xt=urn:btih:BBBB")
    assert rel.details_loaded_at is not None
    other = db.scalar(select(Release).where(Release.title == "Another Film"))
    assert other.variants == []                                                 # only the chosen entry was fetched


@respx.mock
def test_load_versions_never_fetches_another_host(db, source):
    rel = Release(release_key="x", title="Evil", kind="movie", detail_url="http://192.168.0.1/admin",
                  detail_source_id=source.id)
    db.add(rel)
    db.commit()
    route = respx.route().mock(return_value=httpx.Response(200, text=DETAIL))
    with pytest.raises(ValueError, match="different site"), httpx.Client() as c:
        load_versions(db, rel, c)
    rel.detail_url = "file:///etc/passwd"
    with pytest.raises(ValueError, match="different site"), httpx.Client() as c:
        load_versions(db, rel, c)
    assert not route.called


@respx.mock
def test_load_versions_errors_are_clear(db, source):
    rel = Release(release_key="y", title="Empty", kind="movie")
    db.add(rel)
    db.commit()
    with pytest.raises(ValueError, match="no detail page"), httpx.Client() as c:
        load_versions(db, rel, c)
    rel.detail_url, rel.detail_source_id = "https://films.example/m/9", source.id
    respx.get("https://films.example/m/9").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(ValueError, match="'detail' selectors"), httpx.Client() as c:
        load_versions(db, rel, c)


@respx.mock
def test_api_flow_needs_versions_then_load(api_client, db, source, monkeypatch):
    respx.get("https://films.example/list").mock(return_value=httpx.Response(200, text=LISTING))
    respx.get("https://films.example/m/1").mock(return_value=httpx.Response(200, text=DETAIL))
    with httpx.Client() as c:
        scan_source(db, source, c, sleep=lambda _: None)
    cards = {c["title"]: c for c in api_client.get("/api/releases").json()}
    assert cards["Sample Film"]["needs_versions"] is True and cards["Sample Film"]["variants"] == []
    rid = cards["Sample Film"]["id"]
    r = api_client.post(f"/api/releases/{rid}/load-versions")
    assert r.status_code == 200 and r.json() == {"added": 3, "versions": 3}
    card = {c["title"]: c for c in api_client.get("/api/releases").json()}["Sample Film"]
    assert card["needs_versions"] is False and [v["seeders"] for v in card["variants"]] == [310, 40, 12]  # ranked
    respx.get("https://films.example/m/2").mock(return_value=httpx.Response(500))
    other = cards["Another Film"]["id"]
    assert api_client.post(f"/api/releases/{other}/load-versions").status_code == 502
    assert api_client.post("/api/releases/9999/load-versions").status_code == 404


@respx.mock
def test_sources_without_detail_config_behave_as_before(db):
    src = Source(name="flat", url="https://flat.example/", mode="html",
                 selectors={"item": "div.entry", "title": "a.t", "link": "a.t@href"})
    db.add(src)
    db.commit()
    respx.get("https://flat.example/").mock(return_value=httpx.Response(200, text=LISTING))
    with httpx.Client() as c:
        scan_source(db, src, c, sleep=lambda _: None)
    assert db.scalar(select(Release).where(Release.title == "Sample Film")).detail_url is None
    assert len(db.scalars(select(Variant)).all()) == 2                          # old behaviour: link-only variants


def test_sources_api_accepts_and_validates_the_detail_block(api_client):
    body = {"name": "t", "url": "https://films.example/", "mode": "html", "selectors": SEL}
    r = api_client.post("/api/sources", json=body)
    assert r.status_code == 201 and r.json()["selectors"]["detail"]["magnet"] == "a.mag@href"   # nested block kept
    sid = r.json()["id"]
    assert api_client.put(f"/api/sources/{sid}", json=body).status_code == 200
    for bad in ({"detail": "div.ver"}, {"detail": {"item": "div"}}, {"detail": {"item": "a", "title": 5}}, {"item": 3}):
        r = api_client.post("/api/sources", json={**body, "selectors": {**SEL, **bad}})
        assert r.status_code == 422, bad
