from collections.abc import Sequence
from typing import Protocol

TOP_N = 5
_QUALITY_ORDER = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1}


class _V(Protocol):
    seeders: int | None
    quality: str | None
    size_bytes: int | None


def rank_variants[V: _V](variants: Sequence[V], preferred_quality: str = "1080p",
                         limit: int | None = TOP_N) -> list[V]:
    """Seeders desc (unknown last); tie-break preferred quality, then size desc."""
    def key(v: V) -> tuple[int, int, int, int]:
        has = v.seeders is not None
        return (
            0 if has else 1,
            -(v.seeders or 0),
            0 if v.quality == preferred_quality else 1,
            -(v.size_bytes or 0),
        )
    ranked = sorted(variants, key=key)
    return ranked if limit is None else ranked[:limit]
