from __future__ import annotations

import re
from pathlib import Path

from ..parsing.dedupe import normalize_title

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_YEAR_SUFFIX = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")


def safe_name(name: str) -> str:
    cleaned = _BAD.sub(" ", name)
    return re.sub(r"\s+", " ", cleaned).strip(" .")


def movie_dest(root: Path, title: str, year: int | None, ext: str) -> Path:
    base = safe_name(f"{title} ({year})" if year else title)
    return root / base / f"{base}{ext}"


def find_show_dir(root: Path, title: str) -> Path | None:
    """Reuse an existing show folder (case/punctuation/year-insensitive)."""
    if not root.is_dir():
        return None
    want = normalize_title(title)
    for d in sorted(root.iterdir()):
        if d.is_dir() and normalize_title(_YEAR_SUFFIX.sub("", d.name)) == want:
            return d
    return None


def episode_dest(root: Path, show: str, season: int, episode: int, ext: str) -> Path:
    show_dir = find_show_dir(root, show) or root / safe_name(show)
    show_name = _YEAR_SUFFIX.sub("", show_dir.name)
    return show_dir / f"Season {season:02d}" / f"{show_name} - S{season:02d}E{episode:02d}{ext}"
