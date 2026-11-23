import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .types import RawItem

# selectors: {"item": css, "title": "css[@attr]", "link", "date", "magnet",
#             "torrent", "size", "seeders", "leechers", "title_regex"}  -- all but item/title optional.
# title_regex: optional; if it matches, group 1 (or the whole match) replaces the extracted title text.


NO_SELECTORS_MSG = ("No feed was found for this site and no HTML selectors are set. "
                    "Open Edit and add the 'item' and 'title' selectors (see 'Insert example').")


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
        raise ValueError(NO_SELECTORS_MSG)
    r = client.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    try:
        title_re = re.compile(sel["title_regex"]) if sel.get("title_regex") else None
        nodes = soup.select(sel["item"])
    except (re.error, ValueError, SyntaxError) as e:
        raise ValueError(f"invalid selector or title_regex: {e}") from e
    items: list[RawItem] = []
    for node in nodes:
        title = _pick(node, sel["title"])
        if title and title_re and (m := title_re.search(title)):
            title = (m.group(1) if m.groups() else m.group(0)).strip()
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
