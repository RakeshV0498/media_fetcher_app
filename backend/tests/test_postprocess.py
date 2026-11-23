import httpx
import pytest
import respx
from sqlalchemy import select

from app.download import service
from app.download.client import Progress
from app.download.mock import MockClient
from app.models import Download, Release, Source, Tag, Variant
from app.postprocess.jellyfin import refresh_library
from app.postprocess.mover import NeedsAttention, PathNotAllowed, file_release
from app.postprocess.naming import episode_dest, find_show_dir, movie_dest, safe_name

BIG = 60 * 1024 * 1024


def mk(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    return path


def test_naming(tmp_path):
    assert safe_name('Mission: Impossible?') == "Mission Impossible"
    assert movie_dest(tmp_path, "Dune", 2021, ".mkv") == tmp_path / "Dune (2021)" / "Dune (2021).mkv"
    assert episode_dest(tmp_path, "One Piece", 1, 5, ".mkv") == \
        tmp_path / "One Piece" / "Season 01" / "One Piece - S01E05.mkv"


def test_existing_show_folder_reused_case_and_year_insensitive(tmp_path):
    (tmp_path / "one piece (1999)").mkdir()
    assert find_show_dir(tmp_path, "One Piece") == tmp_path / "one piece (1999)"
    d = episode_dest(tmp_path, "One Piece", 2, 3, ".mkv")
    assert d == tmp_path / "one piece (1999)" / "Season 02" / "one piece - S02E03.mkv"


def test_movie_filed_with_subs_and_samples_skipped(tmp_path):
    dl, lib = tmp_path / "dl", tmp_path / "lib"
    mk(dl / "Dune.2021.1080p" / "Dune.2021.1080p.mkv", BIG)
    mk(dl / "Dune.2021.1080p" / "Dune.2021.1080p.en.srt")
    mk(dl / "Dune.2021.1080p" / "Sample" / "sample.mkv", 1000)
    res = file_release(dl / "Dune.2021.1080p", lib, "movie", "Dune", 2021)
    assert res.ok
    assert (lib / "Dune (2021)" / "Dune (2021).mkv").exists()
    assert (lib / "Dune (2021)" / "Dune (2021).en.srt").exists()
    assert len(res.skipped) == 1


def test_single_episode_goes_to_season_folder(tmp_path):
    dl, lib = tmp_path / "dl", tmp_path / "lib"
    f = mk(dl / "Cool.Show.S02E05.1080p.mkv", BIG)
    res = file_release(f, lib, "tv", "Cool Show", season=None)
    assert [d for _, d in res.moved] == [lib / "Cool Show" / "Season 02" / "Cool Show - S02E05.mkv"]
    assert not f.exists()


def test_season_pack_each_file_filed(tmp_path):
    dl, lib = tmp_path / "dl", tmp_path / "lib"
    for e in (1, 2, 3):
        mk(dl / "pack" / f"Show.S01E0{e}.mkv", BIG)
    res = file_release(dl / "pack", lib, "tv", "Show")
    assert len(res.moved) == 3
    assert (lib / "Show" / "Season 01" / "Show - S01E03.mkv").exists()


def test_absolute_anime_without_season_needs_attention_and_touches_nothing(tmp_path):
    dl, lib = tmp_path / "dl", tmp_path / "lib"
    f = mk(dl / "[SubsPlease] One Piece - 1056 (1080p).mkv", BIG)
    with pytest.raises(NeedsAttention):
        file_release(f, lib, "anime", "One Piece")
    assert f.exists() and not lib.exists()
    # manual override of season/episode resolves it
    res = file_release(f, lib, "anime", "One Piece", season=21, episode=1056)
    assert res.moved[0][1] == lib / "One Piece" / "Season 21" / "One Piece - S21E1056.mkv"


def test_duplicate_is_not_overwritten(tmp_path):
    dl, lib = tmp_path / "dl", tmp_path / "lib"
    existing = mk(lib / "Dune (2021)" / "Dune (2021).mkv", 5)
    src = mk(dl / "Dune.2021.mkv", BIG)
    res = file_release(src, lib, "movie", "Dune", 2021)
    assert res.duplicates == [src] and not res.ok
    assert src.exists() and existing.stat().st_size == 5


def test_path_outside_allowed_roots_rejected(tmp_path):
    src = mk(tmp_path / "dl" / "Dune.2021.mkv", BIG)
    with pytest.raises(PathNotAllowed):
        file_release(src, tmp_path / "elsewhere", "movie", "Dune", 2021, allowed_roots=[tmp_path / "lib"])
    file_release(src, tmp_path / "lib" / "movies", "movie", "Dune", 2021, allowed_roots=[tmp_path / "lib"])


def test_no_video_needs_attention(tmp_path):
    mk(tmp_path / "dl" / "readme.txt")
    with pytest.raises(NeedsAttention):
        file_release(tmp_path / "dl", tmp_path / "lib", "movie", "X", 2000)


@respx.mock
def test_jellyfin_refresh():
    route = respx.post("http://jf:8096/Library/Refresh").mock(return_value=httpx.Response(204))
    assert refresh_library("http://jf:8096/", "key") is True
    assert route.calls[0].request.headers["X-Emby-Token"] == "key"
    respx.post("http://jf:8096/Library/Refresh").mock(side_effect=httpx.ConnectError("x"))
    assert refresh_library("http://jf:8096", "key") is False
    assert refresh_library("", "") is False


class FinishedClient(MockClient):
    def __init__(self, path):
        super().__init__()
        self.path, self.removed = path, []

    def status(self, cid):
        return Progress(cid, "done", 1.0, 0, 0, content_path=str(self.path))

    def remove(self, cid, delete_files=False):
        self.removed.append((cid, delete_files))


def _download(db, tmp_path, tag_name, **rel):
    tag = db.scalar(select(Tag).where(Tag.name == tag_name))
    tag.final_path = str(tmp_path / "lib")
    src = Source(name="s", url="u")
    db.add(src)
    db.flush()
    r = Release(release_key="k", **rel)
    db.add(r)
    db.flush()
    v = Variant(release_id=r.id, source_id=src.id, ident="i", magnet="magnet:?xt=urn:btih:1")
    db.add(v)
    db.flush()
    d = Download(release_id=r.id, variant_id=v.id, tag_id=tag.id, client_id="c1", status="downloading")
    db.add(d)
    db.commit()
    return d


def test_finalize_stops_torrent_keeps_files_files_and_refreshes(db, tmp_path, monkeypatch):
    f = mk(tmp_path / "dl" / "Cool.Show.S01E02.1080p.mkv", BIG)
    d = _download(db, tmp_path, "TV Show", title="Cool Show", kind="tv", season=1, episode=2)
    client = FinishedClient(f)
    calls = []
    monkeypatch.setattr(service, "refresh_library", lambda *a, **k: calls.append(1) or True)
    assert service.process_completed(db, client) == 1
    assert d.status == "done" and client.removed == [("c1", False)]  # stopped, files kept
    assert (tmp_path / "lib" / "Cool Show" / "Season 01" / "Cool Show - S01E02.mkv").exists()
    assert calls == [1] and d.final_files


def test_finalize_error_states_and_retry(db, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "refresh_library", lambda *a, **k: True)
    f = mk(tmp_path / "dl" / "[Grp] One Piece - 1056 (1080p).mkv", BIG)
    d = _download(db, tmp_path, "Anime", title="One Piece", kind="tv")
    service.finalize(db, d, FinishedClient(f))
    assert d.status == "needs_attention" and "season" in d.error and f.exists()
    d.release.season, d.release.episode = 21, 1056  # user sets season, then retry
    service.finalize(db, d, FinishedClient(f))
    assert d.status == "done"
    assert (tmp_path / "lib" / "One Piece" / "Season 21" / "One Piece - S21E1056.mkv").exists()
    # duplicate on a second identical download
    f2 = mk(tmp_path / "dl2" / "[Grp] One Piece - 1056 (720p).mkv", BIG)
    d.status, d.content_path = "downloading", ""
    service.finalize(db, d, FinishedClient(f2))
    assert d.status == "duplicate" and f2.exists()


def test_finalize_missing_files_marks_failed(db, tmp_path):
    d = _download(db, tmp_path, "English Movie", title="Dune", kind="movie", year=2021)
    service.finalize(db, d, FinishedClient(tmp_path / "gone.mkv"))
    assert d.status == "failed" and "not found" in d.error
