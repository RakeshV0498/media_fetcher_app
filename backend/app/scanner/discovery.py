from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

COMMON_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/feed/")
_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml")


def _is_feed(client: httpx.Client, url: str) -> bool:
    try:
        r = client.get(url)
    except httpx.HTTPError:
        return False
    if r.status_code != 200:
        return False
    parsed = feedparser.parse(r.content)
    return bool(parsed.entries) or (bool(parsed.version) and not parsed.bozo)


def discover_feed(client: httpx.Client, site_url: str) -> str | None:
    """Return a feed URL for the site, or None (caller falls back to HTML scraping)."""
    try:
        r = client.get(site_url)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            for link in soup.find_all("link", rel=True):
                rels = link.get("rel") or []
                if "alternate" in rels and (link.get("type") or "").lower() in _FEED_TYPES:
                    href = link.get("href")
                    if href:
                        cand = urljoin(site_url, href)
                        if _is_feed(client, cand):
                            return cand
    except httpx.HTTPError:
        pass
    for path in COMMON_PATHS:
        cand = urljoin(site_url, path)
        if _is_feed(client, cand):
            return cand
    return None
