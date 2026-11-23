from __future__ import annotations

import re
from dataclasses import dataclass

from guessit import guessit

_SIZE = re.compile(r"([\d.,]+)\s*(KB|MB|GB|TB|KiB|MiB|GiB|TiB)\b", re.I)
_UNITS = {"kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
          "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}


@dataclass
class ParsedTitle:
    title: str
    kind: str  # movie | tv
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    absolute_episode: int | None = None
    quality: str | None = None
    codec: str | None = None
    language: str | None = None
    raw: str = ""


def parse_size(text: str | None) -> int | None:
    if not text:
        return None
    m = _SIZE.search(text)
    if not m:
        return int(text) if text.strip().isdigit() else None
    return int(float(m.group(1).replace(",", "")) * _UNITS[m.group(2).lower()])


def _first(v: object) -> object:
    return v[0] if isinstance(v, list) and v else v


def parse_title(raw: str) -> ParsedTitle:
    g = guessit(raw)
    episode = _first(g.get("episode"))
    season = _first(g.get("season"))
    kind = "tv" if g.get("type") == "episode" else "movie"
    absolute = None
    # Anime-style bare absolute numbers (e.g. "One Piece - 1056") have no season.
    if kind == "tv" and season is None and isinstance(episode, int) and episode > 99:
        absolute = episode
    lang = g.get("language")
    if isinstance(lang, list):
        lang = lang[0] if lang else None
    return ParsedTitle(
        title=str(g.get("title") or raw).strip(),
        kind=kind,
        year=g.get("year"),
        season=season if isinstance(season, int) else None,
        episode=episode if isinstance(episode, int) else None,
        absolute_episode=absolute,
        quality=g.get("screen_size"),
        codec=g.get("video_codec"),
        language=str(lang) if lang else None,
        raw=raw,
    )
