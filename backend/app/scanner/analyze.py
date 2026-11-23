"""Selector auto-detection: look at a page and propose the selector config the scanner needs.

Generic heuristics only (no site-specific code): find the repeating group of entries, then work out where each entry's
title / link / magnet / torrent / size / seeders live. Every proposal is verified by running the real extraction code
(`parse_html`) on the page and returning a preview, so the user sees exactly what a scan would read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean

from bs4 import BeautifulSoup, Tag

from .html import parse_html

MAGNET = "a[href^='magnet:']"
TORRENT = "a[href*='.torrent']"
_SIZE_FULL = re.compile(r"^\s*[\d.,]+\s*(?:[KMGT]i?B)\s*$", re.I)
_QUALITY = re.compile(r"\b(?:2160p|4k|1080p|720p|480p)\b", re.I)
_CSS_IDENT = re.compile(r"^-?[A-Za-z_][\w-]*$")
_NOT_ITEMS = {"td", "th", "a", "span", "img", "option", "script", "style", "br", "hr", "link", "meta", "source"}
_CHROME_TAGS = {"nav", "header", "footer", "aside", "menu"}
_CHROME_CLASS = re.compile(r"(^|[-_ ])(nav|navbar|menu|footer|sidebar|breadcrumbs?|pagination|tabs?|filters?)([-_ ]|$)", re.I)
MAX_CANDIDATES = 3

FIELD_HEADERS = {  # table header text -> field
    "seeders": re.compile(r"^(s|se|seed|seeds|seeders?)$", re.I),
    "leechers": re.compile(r"^(l|le|leech|leeches|leechers?|peers?)$", re.I),
    "size": re.compile(r"size", re.I),
    "date": re.compile(r"date|added|age|time", re.I),
}
FIELD_CLASSES = {
    "seeders": re.compile(r"seed", re.I),
    "leechers": re.compile(r"leech|peer", re.I),
    "size": re.compile(r"size", re.I),
    "date": re.compile(r"date|time|added", re.I),
}


@dataclass
class Candidate:
    selectors: dict[str, str]
    score: float
    count: int
    notes: list[str] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    two_level: bool = False

    def as_dict(self) -> dict:
        return {"selectors": self.selectors, "score": round(self.score, 1), "count": self.count, "notes": self.notes,
                "preview": self.preview, "stats": self.stats, "two_level": self.two_level}


# ---------------------------------------------------------------- helpers
def _classes(el: Tag) -> list[str]:
    return [c for c in (el.get("class") or []) if _CSS_IDENT.match(c)]


def _tags(el: Tag) -> list[Tag]:
    return [c for c in el.children if isinstance(c, Tag)]


def _text(el: Tag) -> str:
    return el.get_text(" ", strip=True)


def _in_chrome(el: Tag) -> bool:
    for p in [el, *el.parents]:
        if isinstance(p, Tag) and (p.name in _CHROME_TAGS or _CHROME_CLASS.search(" ".join(p.get("class") or []))):
            return True
    return False


def _tag_sel(el: Tag) -> str:
    if el.get("id") and _CSS_IDENT.match(el["id"]):
        return f"#{el['id']}"
    return el.name + "".join(f".{c}" for c in _classes(el))


def _path_to(el: Tag, depth: int = 3) -> str:
    parts: list[str] = []
    cur: Tag | None = el
    while cur is not None and cur.name not in ("[document]", "html", "body") and len(parts) < depth:
        parts.append(_tag_sel(cur))
        if cur.get("id"):
            break
        cur = cur.parent if isinstance(cur.parent, Tag) else None
    return " > ".join(reversed(parts))


def _rel_sel(el: Tag, item: Tag) -> str:
    """A selector for `el` that resolves, inside `item`, to exactly that element."""
    if el is item:
        return ""
    parent = el.parent
    options = [f"{el.name}.{c}" for c in _classes(el)]
    if parent is not item and isinstance(parent, Tag):  # parent-qualified is sturdier than a bare tag name
        options.append(f"{_tag_sel(parent)} > {el.name}")
    options.append(el.name)
    same = [c for c in _tags(parent) if c.name == el.name]
    pos = f"{el.name}:nth-of-type({same.index(el) + 1})"
    options.append(pos if parent is item else f"{_rel_sel(parent, item)} > {pos}")
    for o in options:
        try:
            if item.select_one(o) is el:
                return o
        except Exception:  # invalid selector from odd class names
            continue
    return options[-1]


def _anchors(item: Tag) -> list[Tag]:
    return [a for a in item.find_all("a", href=True)]


def _is_download_link(a: Tag) -> bool:
    h = a["href"]
    return h.startswith("magnet:") or ".torrent" in h.lower()


def _title_anchor(item: Tag) -> Tag | None:
    best: Tag | None = None
    for a in _anchors(item):
        if _is_download_link(a):
            continue
        t = _text(a)
        if len(t) >= 6 and (best is None or len(t) > len(_text(best))):
            best = a
    return best


def _own_text(el: Tag) -> str:
    """Text of el without the text of nested links."""
    clone = BeautifulSoup(str(el), "lxml")
    for a in clone.find_all("a"):
        a.decompose()
    return clone.get_text(" ", strip=True)


# ---------------------------------------------------------------- finding the repeating entries
def _groups(soup: BeautifulSoup, min_n: int = 3):
    for parent in soup.find_all(True):
        by: dict[tuple, list[Tag]] = {}
        for c in _tags(parent):
            by.setdefault((c.name, tuple(sorted(c.get("class") or []))), []).append(c)
        for (name, _), els in by.items():
            if name in _NOT_ITEMS:
                continue
            if name == "tr":  # drop header rows
                els = [e for e in els if e.find("td")]
            if len(els) >= min_n:
                yield parent, els


def _item_selector(soup: BeautifulSoup, parent: Tag, els: list[Tag]) -> str | None:
    first = els[0]
    cands = [_tag_sel(first), f"{_tag_sel(parent)} > {_tag_sel(first)}", f"{_path_to(parent)} > {_tag_sel(first)}"]
    if first.name == "tr":
        cands = [c + ":has(td)" for c in cands] + cands
    want = {id(e) for e in els}
    for sel in cands:
        try:
            found = soup.select(sel)
        except Exception:
            continue
        got = {id(e) for e in found}
        if want <= got and len(found) <= len(els) * 1.3:
            return sel
    return None


# ---------------------------------------------------------------- finding the fields inside an entry
def _header_map(item: Tag) -> dict[str, int]:
    """For table rows: map field -> 1-based column using the header cells."""
    table = item.find_parent("table")
    if table is None:
        return {}
    head = table.find("tr", recursive=True)
    for tr in table.find_all("tr"):
        if tr.find("th"):
            head = tr
            break
    cells = head.find_all(["th", "td"]) if head else []
    out: dict[str, int] = {}
    for i, c in enumerate(cells, start=1):
        label = _text(c)
        for fld, rx in FIELD_HEADERS.items():
            if fld not in out and label and rx.search(label):
                out[fld] = i
    return out


def _field_selectors(item: Tag) -> tuple[dict[str, str], list[str]]:
    sel: dict[str, str] = {}
    notes: list[str] = []
    ta = _title_anchor(item)
    if ta is not None:
        sel["title"] = _rel_sel(ta, item) or "a"
        sel["link"] = sel["title"] + "@href"
    else:  # no suitable link text (e.g. "Name (torrent file) (magnet)"): the element holding the name
        holder = next((t for t in [*_tags(item), item] if len(_own_text(t)) >= 6), None)
        if holder is not None:
            sel["title"] = _rel_sel(holder, item) or item.name
            inner = [a for a in holder.find_all("a") if _text(a)]
            if inner and not _text(holder).startswith(_text(inner[0])):
                sel["title_regex"] = r"^(.*?)\s*" + re.escape(_text(inner[0]))
                notes.append("Trimmed the trailing link text from the title with title_regex.")
    if item.select_one(MAGNET):
        sel["magnet"] = f"{MAGNET}@href"
    if item.select_one(TORRENT):
        sel["torrent"] = f"{TORRENT}@href"

    headers = _header_map(item) if item.name == "tr" else {}
    for fld in ("size", "seeders", "leechers", "date"):
        if fld in headers:
            sel[fld] = f"td:nth-child({headers[fld]})"
            continue
        el = next((e for e in item.find_all(True, class_=FIELD_CLASSES[fld]) if _text(e)), None)
        if el is None and fld == "size":
            el = next((e for e in item.find_all(True) if not _tags(e) and _SIZE_FULL.match(_text(e))), None)
        if el is not None:
            sel[fld] = _rel_sel(el, item)
    return sel, notes


def _verify(html: str, base_url: str, sel: dict[str, str]) -> tuple[list[dict], dict[str, int]]:
    try:
        items = parse_html(html, base_url, sel)
    except ValueError:
        return [], {}
    preview = [{"title": i.title, "link": i.link, "magnet": bool(i.magnet), "torrent": bool(i.torrent_url),
                "size": i.size_text, "seeders": i.seeders, "leechers": i.leechers} for i in items[:6]]
    n = len(items)
    stats = {"items": n, "with_link": sum(1 for i in items if i.link),
             "with_magnet": sum(1 for i in items if i.magnet), "with_torrent": sum(1 for i in items if i.torrent_url),
             "with_size": sum(1 for i in items if i.size_text), "with_seeders": sum(1 for i in items if i.seeders is not None)}
    return preview, stats


# ---------------------------------------------------------------- listing pages
def _listing_candidates(soup: BeautifulSoup, html: str, base_url: str, min_n: int) -> list[Candidate]:
    cands: list[Candidate] = []
    seen: set[str] = set()
    for parent, els in _groups(soup, min_n):
        anchored = [e for e in els if _title_anchor(e) or _own_text(e)]
        if len(anchored) / len(els) < 0.7:
            continue
        n = len(els)
        has_mag = sum(1 for e in els if e.select_one(MAGNET)) / n
        has_tor = sum(1 for e in els if e.select_one(TORRENT)) / n
        hrefs = {a["href"] for e in els for a in [_title_anchor(e)] if a is not None}
        distinct = len(hrefs) / n if hrefs else 1.0
        avg_len = mean(len(_text(e)) for e in els)
        score = min(n, 100) + 25 * has_mag + 25 * has_tor + min(avg_len, 140) / 7 + 10 * distinct
        if _in_chrome(parent):
            score *= 0.15
        if distinct < 0.5:
            score *= 0.4
        if score < 8:
            continue
        sel_item = _item_selector(soup, parent, els)
        if not sel_item or sel_item in seen:
            continue
        seen.add(sel_item)
        fields, notes = _field_selectors(els[0])
        if "title" not in fields:
            continue
        selectors = {"item": sel_item, **fields}
        preview, stats = _verify(html, base_url, selectors)
        if not stats or stats["items"] == 0:
            continue
        c = Candidate(selectors=selectors, score=score, count=stats["items"], notes=notes, preview=preview, stats=stats)
        if stats["with_magnet"] == 0 and stats["with_torrent"] == 0 and stats["with_link"] > 0:
            c.two_level = True
            c.notes.append("These entries have no magnet or .torrent link on this page. This looks like a site where each "
                           "title has its own page: use 'Detect versions' on a sample entry to configure the 'detail' part.")
        cands.append(c)
    return cands


def analyze_listing(html: str, base_url: str = "") -> tuple[list[Candidate], list[str]]:
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []
    # Lists of 3+ entries first (menus are usually 2); only accept 2-entry lists if nothing better exists.
    cands = _listing_candidates(soup, html, base_url, 3) or _listing_candidates(soup, html, base_url, 2)
    cands.sort(key=lambda c: -c.score)
    if not cands:
        warnings.append("No repeating list of entries was found. If the page's source (Ctrl+U) doesn't contain the entries, "
                        "the site builds the list with JavaScript, which this scraper can't read; if it needs a login, "
                        "save the page and use 'Paste page HTML'.")
    return cands[:MAX_CANDIDATES], warnings


# ---------------------------------------------------------------- detail pages (several versions of one title)
def _version_block(a: Tag) -> Tag | None:
    """Largest ancestor of this download link that still holds only one magnet and one torrent link."""
    best: Tag | None = None
    cur = a.parent
    while isinstance(cur, Tag) and cur.name not in ("body", "html", "[document]"):
        if len(cur.select(MAGNET)) > 1 or len(cur.select(TORRENT)) > 1:
            break
        best = cur
        cur = cur.parent
    return best


def _detail_fields(block: Tag) -> dict[str, str]:
    sel: dict[str, str] = {}
    leaves = [e for e in block.find_all(True) if _text(e)]
    titled = [e for e in leaves if _QUALITY.search(_text(e))]
    if titled:
        deepest = min(titled, key=lambda e: len(_text(e)))  # the tightest element still showing the quality
        sel["title"] = _rel_sel(deepest, block) or deepest.name
    elif _title_anchor(block) is not None:
        sel["title"] = _rel_sel(_title_anchor(block), block)
    else:
        sel["title"] = block.name
    if block.select_one(MAGNET):
        sel["magnet"] = f"{MAGNET}@href"
    if block.select_one(TORRENT):
        sel["torrent"] = f"{TORRENT}@href"
    for fld in ("size", "seeders", "leechers"):
        el = next((e for e in block.find_all(True, class_=FIELD_CLASSES[fld]) if _text(e)), None)
        if el is None and fld == "size":
            el = next((e for e in block.find_all(True) if not _tags(e) and _SIZE_FULL.match(_text(e))), None)
        if el is not None:
            sel[fld] = _rel_sel(el, block)
    return sel


def analyze_detail(html: str, base_url: str = "") -> tuple[list[Candidate], list[str]]:
    soup = BeautifulSoup(html, "lxml")
    links = soup.select(f"{MAGNET}, {TORRENT}")
    if not links:
        return [], ["No magnet or .torrent links were found on this page. If they only appear after a click or via "
                    "JavaScript, they can't be read; use 'Paste page HTML' with the page as you see it."]
    blocks: list[Tag] = []
    for a in links:
        b = _version_block(a)
        if b is not None and not any(b is x for x in blocks):
            blocks.append(b)
    by_sig: dict[tuple, list[Tag]] = {}
    for b in blocks:
        by_sig.setdefault((b.name, tuple(sorted(b.get("class") or []))), []).append(b)
    cands: list[Candidate] = []
    for els in sorted(by_sig.values(), key=len, reverse=True):
        parent = els[0].parent
        sel_item = _item_selector(soup, parent, els) if len(els) >= 2 else _tag_sel(els[0])
        if not sel_item:
            continue
        fields, _ = _field_selectors_detail(els[0])
        selectors = {"item": sel_item, **fields}
        preview, stats = _verify(html, base_url, selectors)
        if not stats or stats["items"] == 0:
            continue
        got_links = stats["with_magnet"] + stats["with_torrent"]
        score = stats["items"] * 10 + got_links * 5 + stats["with_size"] + stats["with_seeders"]
        cands.append(Candidate(selectors=selectors, score=score, count=stats["items"], preview=preview, stats=stats))
    flat = _flat_candidate(soup, html, base_url)
    if flat is not None and (not cands or flat.count > max(c.count for c in cands)):
        cands.append(flat)  # versions listed one after another, not in separate boxes
    cands.sort(key=lambda c: -c.score)
    warnings = []
    if not cands:
        warnings.append("Download links exist, but the versions couldn't be told apart automatically. Use 'Paste page "
                        "HTML' with the page as you see it, or write the selectors by hand.")
    return cands[:MAX_CANDIDATES], warnings


def _common_ancestor(els: list[Tag]) -> Tag | None:
    chains = [list(reversed([e, *[p for p in e.parents if isinstance(p, Tag)]])) for e in els]
    common = None
    for group in zip(*chains):
        if all(g is group[0] for g in group):
            common = group[0]
        else:
            break
    return common


def _flat_candidate(soup: BeautifulSoup, html: str, base_url: str) -> Candidate | None:
    """Versions that follow each other inside one container (title line, .torrent link, magnet button, next title ...).
    Each download link starts a version; the magnet is the next magnet after it, the title the text before it."""
    torrents, magnets = soup.select(TORRENT), soup.select(MAGNET)
    if torrents and len(torrents) >= len(magnets):
        css, anchors = TORRENT, torrents
    elif magnets:
        css, anchors = MAGNET, magnets
    else:
        return None
    lca = _common_ancestor(anchors) if len(anchors) > 1 else anchors[0].parent
    scope = ""
    if isinstance(lca, Tag) and lca.name not in ("body", "html", "[document]"):
        scope = _path_to(lca) + " "
    sel: dict[str, str] = {"item": scope + css}
    if css == TORRENT:
        sel["torrent"] = "@href"
        if magnets:
            sel["magnet"] = f"next:{MAGNET}@href"
        name = _text(anchors[0])
        sel["title"] = "self" if (_QUALITY.search(name) or len(name) >= 14) else "prevtext"
    else:
        sel["magnet"] = "@href"
        sel["title"] = "prevtext"
    preview, stats = _verify(html, base_url, sel)
    if not stats or stats["items"] == 0:
        return None
    got = stats["with_magnet"] + stats["with_torrent"]
    return Candidate(
        selectors=sel, score=stats["items"] * 10 + got * 5, count=stats["items"], preview=preview, stats=stats,
        notes=["The versions are listed one after another (not in separate boxes), so each download link starts a "
               "version and its title is read from the text just before it. Check the titles in the preview."])


def _field_selectors_detail(block: Tag) -> tuple[dict[str, str], list[str]]:
    return _detail_fields(block), []
