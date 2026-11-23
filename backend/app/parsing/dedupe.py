import re
import unicodedata

from .parser import ParsedTitle


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def release_key(p: ParsedTitle) -> str:
    name = normalize_title(p.title)
    if p.kind == "movie":
        return f"movie:{name}:{p.year or ''}"
    if p.season is not None and p.episode is not None:
        return f"tv:{name}:s{p.season:02d}e{p.episode:03d}"
    if p.absolute_episode is not None:
        return f"tv:{name}:abs{p.absolute_episode}"
    return f"tv:{name}:e{p.episode if p.episode is not None else ''}:{p.year or ''}"
