from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .types import RawItem

# selectors: {"item": css, "title": "css[@attr]", "link", "date", "magnet",
#             "torrent", "size", "seeders", "leechers"}  -- all but item/title optional.


def _pick(node: Tag, spec: str | None) -> str | None:
    if not spec:
        return None
    css, _, attr = spec.partition("@")
    el = node.select_one(css.strip()) if css.strip() else node
    if el is None:
        return None
    val = el.get(attr.strip()) if attr else el.get_text(" ", strip=True)
    if isinstance(val, list):
        val = " ".join(val)
    return val or None


def _int(v: str | None) -> int | None:
    if not v:
        return None
    digits = "".join(c for c in v if c.isdigit())
    return int(digits) if digits else None


def fetch_html(client: httpx.Client, url: str, sel: dict[str, str]) -> list[RawItem]:
    if not sel.get("item") or not sel.get("title"):
        raise ValueError("html mode needs 'item' and 'title' selectors")
    r = client.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    items: list[RawItem] = []
    for node in soup.select(sel["item"]):
        title = _pick(node, sel["title"])
        if not title:
            continue

        def url_of(key: str) -> str | None:
            v = _pick(node, sel.get(key))
            return v if v is None or v.startswith("magnet:") else urljoin(url, v)

        magnet = url_of("magnet")
        link = url_of("link")
        if link and link.startswith("magnet:"):
            magnet, link = magnet or link, None
        items.append(RawItem(
            title=title, link=link, magnet=magnet, torrent_url=url_of("torrent"),
            size_text=_pick(node, sel.get("size")),
            seeders=_int(_pick(node, sel.get("seeders"))),
            leechers=_int(_pick(node, sel.get("leechers"))),
            published=_pick(node, sel.get("date")),
        ))
    return [i for i in items if i.magnet or i.torrent_url or i.link]
