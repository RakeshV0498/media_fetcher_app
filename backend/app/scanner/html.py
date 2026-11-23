import re
from urllib.parse import urljoin

import httpx
import soupsieve as sv
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .types import RawItem

# selectors: {"item": css, "title": "css[@attr]", "link", "date", "magnet",
#             "torrent", "size", "seeders", "leechers", "title_regex"}  -- all but item/title optional.
# title_regex: optional; if it matches, group 1 (or the whole match) replaces the extracted title text.


NO_SELECTORS_MSG = ("No feed was found for this site and no HTML selectors are set. "
                    "Open Edit and add the 'item' and 'title' selectors (see 'Insert example').")


def _inside(el, ancestor) -> bool:
    return ancestor is not None and (el is ancestor or any(p is ancestor for p in el.parents))


def _neighbours(node: Tag, forward: bool, prev_b: Tag | None, next_b: Tag | None):
    """Elements after/before `node` in document order, kept inside its parent and short of the neighbouring item.
    Lets a flat page (title line, torrent link, magnet button, next title line, ...) be read without wrapper blocks."""
    scope = node.parent
    boundary = next_b if forward else prev_b
    for el in (node.next_elements if forward else node.previous_elements):
        if forward and _inside(el, node):
            continue  # the node's own descendants
        if boundary is not None and _inside(el, boundary):
            return
        if scope is not None and (el is scope if not forward else not _inside(el, scope)):
            return
        yield el


def _pick(node: Tag, spec: str | None, prev_b: Tag | None = None, next_b: Tag | None = None) -> str | None:
    """Extract text or an attribute. Forms: `css[@attr]` (inside the item), `self[@attr]` (the item itself),
    `next:css[@attr]` / `prev:css[@attr]` (nearest match after/before the item, within its container and before the
    neighbouring item), and `prevtext` (nearest preceding line of text, e.g. a title written before its links)."""
    if not spec:
        return None
    if spec.strip() == "prevtext":
        for el in _neighbours(node, False, prev_b, next_b):
            if isinstance(el, NavigableString) and not isinstance(el, Comment) and el.parent.name not in ("script", "style"):
                t = str(el).strip()
                if len(t) >= 8:
                    return t
        return None
    css, _, attr = spec.partition("@")
    css = css.strip()
    el: Tag | None
    if css in ("", "self"):
        el = node
    elif css.startswith(("next:", "prev:")):
        want = css[5:].strip()
        el = None
        for cand in _neighbours(node, css.startswith("next:"), prev_b, next_b):
            if isinstance(cand, Tag) and sv.match(want, cand):
                el = cand
                break
    else:
        el = node.select_one(css)
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
    return parse_html(r.text, url, sel)


def parse_html(html: str, url: str, sel: dict[str, str]) -> list[RawItem]:
    """Apply a selector config to a page's HTML (the same code path scans and the auto-detector use)."""
    if not sel.get("item") or not sel.get("title"):
        raise ValueError(NO_SELECTORS_MSG)
    soup = BeautifulSoup(html, "lxml")
    try:
        title_re = re.compile(sel["title_regex"]) if sel.get("title_regex") else None
        nodes = soup.select(sel["item"])
    except (re.error, ValueError, SyntaxError) as e:
        raise ValueError(f"invalid selector or title_regex: {e}") from e
    items: list[RawItem] = []
    for idx, node in enumerate(nodes):
        pb = nodes[idx - 1] if idx > 0 else None
        nb = nodes[idx + 1] if idx + 1 < len(nodes) else None

        def pick(key: str, node=node, pb=pb, nb=nb) -> str | None:
            return _pick(node, sel.get(key), pb, nb)

        title = pick("title")
        if title and title_re and (m := title_re.search(title)):
            title = (m.group(1) if m.groups() else m.group(0)).strip()
        if not title:
            continue

        def url_of(key: str) -> str | None:
            v = pick(key)
            return v if v is None or v.startswith("magnet:") else urljoin(url, v)

        magnet = url_of("magnet")
        link = url_of("link")
        if link and link.startswith("magnet:"):
            magnet, link = magnet or link, None
        items.append(RawItem(
            title=title, link=link, magnet=magnet, torrent_url=url_of("torrent"),
            size_text=pick("size"),
            seeders=_int(pick("seeders")),
            leechers=_int(pick("leechers")),
            published=pick("date"),
        ))
    return [i for i in items if i.magnet or i.torrent_url or i.link]
