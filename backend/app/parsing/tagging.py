from .parser import ParsedTitle

_ANIME_HINTS = ("anime", "subbed", "dual audio", "erai-raws", "subsplease")


def suggest_tag_name(p: ParsedTitle, raw_title: str = "") -> str:
    low = raw_title.lower()
    lang = (p.language or "").lower()
    if p.kind == "tv":
        return "Anime" if any(h in low for h in _ANIME_HINTS) or p.absolute_episode else "TV Show"
    if "dubbed" in low or "dual audio" in low:
        return "Dubbed Movie"
    if lang in ("tamil", "ta") or "tamil" in low:
        return "Tamil Movie"
    if lang in ("hindi", "telugu", "malayalam", "kannada", "hi", "te", "ml", "kn") or any(
            x in low for x in ("hindi", "telugu", "malayalam", "kannada")):
        return "Indian Language Movie"
    return "English Movie"
