"""TMDB + AniList enrichment. Key-optional, cached, never raises into the scan path."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Release, ShowMeta, Tag
from .dedupe import normalize_title

TMDB = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w342"
ANILIST = "https://graphql.anilist.co"
NEG_TTL = timedelta(days=1)
ANIMATION = 16  # TMDB genre id
_ANILIST_Q = """query($s:String){Media(search:$s,type:ANIME){id title{romaji english}
coverImage{large} description genres episodes format countryOfOrigin}}"""


@dataclass
class Meta:
    poster_url: str | None = None
    overview: str | None = None
    genres: list[str] = field(default_factory=list)
    language: str | None = None       # original language code (movies/tv)
    country: str | None = None
    is_anime: bool = False
    season_counts: list[tuple[int, int]] = field(default_factory=list)  # (season, episodes)

    def to_json(self) -> dict:
        return self.__dict__ | {"season_counts": [list(x) for x in self.season_counts]}

    @classmethod
    def from_json(cls, d: dict) -> Meta | None:
        if not d:
            return None
        d = dict(d)
        d["season_counts"] = [tuple(x) for x in d.get("season_counts", [])]
        return cls(**d)


def map_absolute(season_counts: list[tuple[int, int]], absolute: int) -> tuple[int, int] | None:
    """Absolute episode number -> (season, episode) using per-season episode counts (no specials)."""
    if absolute < 1:
        return None
    left = absolute
    for season, count in sorted(season_counts):
        if season == 0:
            continue
        if left <= count:
            return season, left
        left -= count
    return None


class TMDBClient:
    def __init__(self, http: httpx.Client, key: str) -> None:
        self.http, self.key = http, key

    def _get(self, path: str, **params: object) -> dict:
        headers = {}
        if self.key.startswith("eyJ"):  # v4 read token
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        r = self.http.get(f"{TMDB}{path}", params=params, headers=headers)
        r.raise_for_status()
        return r.json()

    def lookup(self, title: str, kind: str, year: int | None, with_seasons: bool) -> Meta | None:
        if kind == "movie":
            res = self._get("/search/movie", query=title, **({"year": year} if year else {}))["results"]
        else:
            res = self._get("/search/tv", query=title)["results"]
        if not res:
            return None
        hit = res[0]
        m = Meta(
            poster_url=f"{IMG}{hit['poster_path']}" if hit.get("poster_path") else None,
            overview=hit.get("overview") or None,
            language=hit.get("original_language"),
            country=(hit.get("origin_country") or [None])[0],
            is_anime=ANIMATION in hit.get("genre_ids", []) and (hit.get("original_language") == "ja"),
            genres=["Animation"] if ANIMATION in hit.get("genre_ids", []) else [],
        )
        if kind == "tv" and with_seasons:
            det = self._get(f"/tv/{hit['id']}")
            m.season_counts = [(s["season_number"], s["episode_count"]) for s in det.get("seasons", [])]
        return m


class AniListClient:
    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def lookup(self, title: str) -> Meta | None:
        r = self.http.post(ANILIST, json={"query": _ANILIST_Q, "variables": {"s": title}})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        media = (r.json().get("data") or {}).get("Media")
        if not media:
            return None
        return Meta(
            poster_url=(media.get("coverImage") or {}).get("large"),
            overview=media.get("description"), genres=media.get("genres") or [],
            language="ja", country=media.get("countryOfOrigin"), is_anime=True)


def suggest_tag_from_meta(kind: str, meta: Meta) -> str | None:
    if kind == "tv":
        return "Anime" if meta.is_anime else "TV Show"
    lang = (meta.language or "").lower()
    if lang == "ta":
        return "Tamil Movie"
    if lang in ("hi", "te", "ml", "kn", "bn", "mr", "pa"):
        return "Indian Language Movie"
    if lang == "en":
        return "English Movie"
    return None


def _cached(db: Session, key: str) -> tuple[bool, Meta | None]:
    row = db.get(ShowMeta, key)
    if row is None:
        return False, None
    meta = Meta.from_json(row.data)
    if meta is None and datetime.now(timezone.utc) - row.fetched_at.replace(tzinfo=timezone.utc) > NEG_TTL:
        return False, None  # stale miss, retry
    return True, meta


def _store(db: Session, key: str, meta: Meta | None) -> None:
    row = db.get(ShowMeta, key) or ShowMeta(key=key)
    row.data = meta.to_json() if meta else {}
    row.fetched_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()


def enrich_release(db: Session, rel: Release, http: httpx.Client, tmdb_key: str | None = None) -> bool:
    """Fill poster/overview/genres, suggest a better tag, resolve absolute -> season. Best effort."""
    tmdb_key = settings.tmdb_api_key if tmdb_key is None else tmdb_key
    need_seasons = rel.kind == "tv" and rel.season is None and rel.absolute_episode is not None
    key = f"{rel.kind}:{normalize_title(rel.title)}:{rel.year or ''}"
    cached, meta = _cached(db, key)
    if cached and meta and need_seasons and not meta.season_counts and tmdb_key:
        cached = False  # cached without seasons but we now need them
    if not cached:
        meta = None
        try:
            if tmdb_key:
                meta = TMDBClient(http, tmdb_key).lookup(rel.title, rel.kind, rel.year, need_seasons)
            anime_hint = rel.kind == "tv" and (rel.absolute_episode is not None or (meta and meta.is_anime)
                                               or meta is None)
            if anime_hint:
                al = AniListClient(http).lookup(rel.title)
                if al and meta is None:
                    meta = al
                elif al and meta:
                    meta.is_anime = True
                    meta.poster_url = meta.poster_url or al.poster_url
                    meta.overview = meta.overview or al.overview
                    meta.genres = sorted(set(meta.genres) | set(al.genres))
        except (httpx.HTTPError, KeyError, ValueError):
            return False  # transient: don't cache, retry next run
        _store(db, key, meta)
    rel.enriched_at = datetime.now(timezone.utc)
    if meta is None:
        db.commit()
        return False
    rel.poster_url, rel.overview, rel.genres = meta.poster_url, meta.overview, meta.genres
    name = suggest_tag_from_meta(rel.kind, meta)
    if name and rel.status == "new":
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag:
            rel.suggested_tag_id = tag.id
    if need_seasons and meta.season_counts:
        mapped = map_absolute(meta.season_counts, rel.absolute_episode)  # type: ignore[arg-type]
        if mapped:
            rel.season, rel.episode = mapped
    db.commit()
    return True


def enrich_pending(db: Session, http: httpx.Client | None = None, limit: int = 20) -> int:
    own = http is None
    http = http or httpx.Client(timeout=15, headers={"User-Agent": settings.user_agent})
    n = 0
    try:
        stmt = select(Release).where(Release.enriched_at.is_(None)).order_by(Release.id).limit(limit)
        for rel in db.scalars(stmt):
            n += enrich_release(db, rel, http)
    finally:
        if own:
            http.close()
    return n
