from app.parsing.parser import parse_size, parse_title
from app.parsing.tagging import suggest_tag_name


def test_movie():
    p = parse_title("Some.Movie.2023.1080p.WEB-DL.x265-GRP")
    assert (p.kind, p.title, p.year, p.quality, p.codec) == ("movie", "Some Movie", 2023, "1080p", "H.265")


def test_episode():
    p = parse_title("Cool Show S02E05 720p HDTV x264")
    assert (p.kind, p.season, p.episode, p.quality) == ("tv", 2, 5, "720p")


def test_anime_absolute():
    p = parse_title("[SubsPlease] One Piece - 1056 (1080p) [ABCD1234].mkv")
    assert p.kind == "tv" and p.absolute_episode == 1056 and p.season is None


def test_size():
    assert parse_size("1.5 GB") == 1_500_000_000
    assert parse_size("700 MiB") == 700 * 1024**2
    assert parse_size("12345") == 12345
    assert parse_size("n/a") is None


def test_tagging():
    def tag(t: str) -> str:
        return suggest_tag_name(parse_title(t), t)

    assert tag("Film 2021 Tamil 1080p") == "Tamil Movie"
    assert tag("Film 2021 1080p") == "English Movie"
    assert tag("Film 2021 Hindi Dubbed 1080p") == "Dubbed Movie"
    assert tag("Show S01E01 1080p") == "TV Show"
    assert tag("[SubsPlease] One Piece - 1056 (1080p)") == "Anime"
