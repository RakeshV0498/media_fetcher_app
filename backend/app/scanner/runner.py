from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Release, Source, Tag, Variant
from ..parsing.dedupe import release_key
from ..parsing.parser import parse_size, parse_title
from ..parsing.tagging import suggest_tag_name
from .discovery import discover_feed
from .feed import fetch_feed
from . import browser_client
from .html import NO_SELECTORS_MSG, parse_html
from .types import RawItem

_locks: dict[int, threading.Lock] = {}
_HASH = re.compile(r"btih:([0-9a-zA-Z]{32,40})")


def make_client(source: Source) -> httpx.Client:
    ua = source.user_agent or settings.user_agent
    return httpx.Client(headers={"User-Agent": ua}, timeout=20, follow_redirects=True)


def get_html(source: Source, url: str, client: httpx.Client) -> tuple[str, str]:
    """The page's HTML and its final URL, fetched the way this source asks for: plain HTTP, or a real browser
    (for sites that build their list with JavaScript)."""
    if source.render == "browser":
        page = browser_client.render(url, wait_selector=source.wait_selector, user_agent=source.user_agent)
        return page.html, page.final_url
    r = client.get(url)
    r.raise_for_status()
    return r.text, str(r.url)


def fetch_items(source: Source, url: str, selectors: dict, client: httpx.Client) -> list[RawItem]:
    if not selectors.get("item") or not selectors.get("title"):
        raise ValueError(NO_SELECTORS_MSG)  # checked first so a misconfigured source never costs a browser render
    html, final_url = get_html(source, url, client)
    return parse_html(html, final_url, selectors)


def _ident(item: RawItem) -> str:
    if item.magnet and (m := _HASH.search(item.magnet)):
        return m.group(1).lower()
    return item.torrent_url or item.link or item.magnet or item.title


def add_variant(db: Session, source: Source, rel: Release, item: RawItem) -> bool:
    """Attach one downloadable version to a release (idempotent; refreshes seeders). True if newly created."""
    p = parse_title(item.title)
    ident = _ident(item)
    var = db.scalar(select(Variant).where(
        Variant.release_id == rel.id, Variant.source_id == source.id, Variant.ident == ident))
    if var is None:
        db.add(Variant(
            release_id=rel.id, source_id=source.id, ident=ident, title=item.title,
            quality=p.quality, codec=p.codec, language=p.language,
            size_bytes=parse_size(item.size_text) or parse_size(item.title), seeders=item.seeders,
            leechers=item.leechers, magnet=item.magnet, torrent_url=item.torrent_url,
            link=item.link))
        return True
    if item.seeders is not None:
        var.seeders = item.seeders
    if item.leechers is not None:
        var.leechers = item.leechers
    var.seen_at = datetime.now(timezone.utc)
    return False


def upsert_items(db: Session, source: Source, items: list[RawItem]) -> int:
    """Insert new releases/variants; refresh seeders on known ones. Returns the number of new entries.

    Sources with a `detail` selector config are two-level sites: listing entries without a magnet/torrent only
    record their detail-page URL; the versions are fetched on demand (see scanner.details.load_versions)."""
    tags = {t.name: t.id for t in db.scalars(select(Tag))}
    two_level = bool((source.selectors or {}).get("detail"))
    new = 0
    for item in items:
        p = parse_title(item.title)
        key = release_key(p)
        rel = db.scalar(select(Release).where(Release.release_key == key))
        created = rel is None
        if rel is None:
            tag_id = source.default_tag_id or tags.get(suggest_tag_name(p, item.title))
            rel = Release(release_key=key, title=p.title, year=p.year, season=p.season,
                          episode=p.episode, absolute_episode=p.absolute_episode,
                          kind=p.kind, suggested_tag_id=tag_id)
            db.add(rel)
            db.flush()
        if two_level and item.link and not (item.magnet or item.torrent_url):
            if not rel.detail_url:
                rel.detail_url, rel.detail_source_id = item.link, source.id
            new += 1 if created else 0
            continue
        if add_variant(db, source, rel, item):
            new += 1
    db.commit()
    return new


def scan_source(db: Session, source: Source, client: httpx.Client | None = None,
                sleep: Callable[[float], None] = time.sleep) -> str:
    lock = _locks.setdefault(source.id, threading.Lock())
    if not lock.acquire(blocking=False):
        return "scan already running"
    own = client is None
    client = client or make_client(source)
    try:
        sleep(random.uniform(settings.scan_min_delay, settings.scan_max_delay))
        items: list[RawItem] = []
        feed_url = source.feed_url
        if source.mode in ("auto", "feed") and not feed_url:
            feed_url = discover_feed(client, source.url)
            if feed_url:
                source.feed_url = feed_url
            elif source.mode == "feed":
                raise ValueError("No feed was found for this site. Switch the source to HTML mode and add selectors, or check the URL.")
        if source.mode != "html" and feed_url:
            items = fetch_feed(client, feed_url)
        else:
            items = fetch_items(source, source.url, source.selectors or {}, client)
        new = upsert_items(db, source, items)
        status = f"ok: {len(items)} items, {new} new"
    except Exception as exc:  # recorded for the UI; never crash the scheduler
        status = f"error: {exc}"
    finally:
        lock.release()
        if own:
            client.close()
    source.last_scan_at = datetime.now(timezone.utc)
    source.last_status = status
    db.commit()
    return status
