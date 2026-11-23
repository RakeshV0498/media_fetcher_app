from dataclasses import dataclass

from app.parsing.dedupe import normalize_title, release_key
from app.parsing.parser import parse_title
from app.parsing.ranking import rank_variants


def test_same_release_different_quality_same_key():
    a = release_key(parse_title("Cool.Show.S01E02.720p.x264"))
    b = release_key(parse_title("Cool Show S01E02 1080p WEB"))
    assert a == b
    assert a != release_key(parse_title("Cool Show S01E03 1080p"))


def test_normalize():
    assert normalize_title("Amélie: The Movie!") == "amelie the movie"


@dataclass
class V:
    seeders: int | None
    quality: str | None = "720p"
    size_bytes: int | None = 1


def test_ranking():
    vs = [V(None), V(5), V(50), V(5, "1080p"), V(1), V(2), V(3)]
    top = rank_variants(vs, "1080p")
    assert len(top) == 5
    assert [v.seeders for v in top] == [50, 5, 5, 3, 2]
    assert top[1].quality == "1080p"  # tie-break on preferred quality
    assert rank_variants(vs, limit=None)[-1].seeders is None
