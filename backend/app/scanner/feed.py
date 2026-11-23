import re

import feedparser
import httpx

from .types import RawItem

_SEED = re.compile(r"seed(?:er)?s?\D{0,3}(\d+)", re.I)
_LEECH = re.compile(r"leech(?:er)?s?\D{0,3}(\d+)", re.I)
_SIZE = re.compile(r"[\d.,]+\s*(?:[KMGT]i?B)\b", re.I)
_MAGNET = re.compile(r"magnet:\?[^\s\"'<>]+")


def _int(v: object) -> int | None:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def fetch_feed(client: httpx.Client, feed_url: str) -> list[RawItem]:
    r = client.get(feed_url)
    r.raise_for_status()
    items: list[RawItem] = []
    for e in feedparser.parse(r.content).entries:
        text = " ".join(str(e.get(k, "")) for k in ("summary", "description", "title"))
        magnet = e.get("torrent_magneturi") or None
        torrent = None
        for enc in e.get("enclosures", []) or []:
            href = enc.get("href", "")
            if href.startswith("magnet:"):
                magnet = magnet or href
            elif "torrent" in (enc.get("type") or "") or href.endswith(".torrent"):
                torrent = href
        link = e.get("link")
        if not magnet:
            m = _MAGNET.search(text) or (_MAGNET.search(link) if link else None)
            magnet = m.group(0) if m else None
        if link and link.startswith("magnet:"):
            magnet, link = magnet or link, None
        if link and link.endswith(".torrent") and not torrent:
            torrent = link
        seeders = _int(e.get("torrent_seeds") or e.get("seeders"))
        leechers = _int(e.get("torrent_peers") or e.get("leechers"))
        if seeders is None and (m := _SEED.search(text)):
            seeders = int(m.group(1))
        if leechers is None and (m := _LEECH.search(text)):
            leechers = int(m.group(1))
        size = e.get("torrent_contentlength") or e.get("size")
        if not size and (m := _SIZE.search(text)):
            size = m.group(0)
        if not size:
            for enc in e.get("enclosures", []) or []:
                if enc.get("length"):
                    size = enc["length"]
        items.append(RawItem(
            title=str(e.get("title", "")).strip(), link=link, magnet=magnet,
            torrent_url=torrent, size_text=str(size) if size else None,
            seeders=seeders, leechers=leechers, published=e.get("published"),
        ))
    return [i for i in items if i.title and (i.magnet or i.torrent_url or i.link)]
