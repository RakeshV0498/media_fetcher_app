import httpx
import pytest
import respx
from sqlalchemy import select

from app.models import Release, Setting, Source
from app.parsing.dedupe import release_key
from app.parsing.parser import parse_title
from app.scanner.html import NO_SELECTORS_MSG, fetch_html
from app.scanner.runner import scan_source
from app.seed import EXAMPLE_SOURCES, seed_example_sources

# Trimmed copy of the structure of the page the example source reads.
PAGE = """<html><body><main><article><h1>Free Torrents</h1><ul>
<li><p>Big Buck Bunny <a href="https://example.test/torrents/big-buck-bunny.torrent">(torrent file)</a>
 <a href="magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&amp;dn=Big+Buck+Bunny">(magnet link)</a></p></li>
<li><p>Sintel <a href="https://example.test/torrents/sintel.torrent">(torrent file)</a>
 <a href="magnet:?xt=urn:btih:08ada5a7a6183aae1e09d831df6748d566095a10&amp;dn=Sintel">(magnet link)</a></p></li>
<li><p>The WIRED CD - Rip. Sample. Mash. Share <a href="https://example.test/torrents/wired-cd.torrent">(torrent file)</a>
 <a href="magnet:?xt=urn:btih:a88fda5954e89178c372716a6a78b8180ed4dad3">(magnet link)</a></p></li>
</ul></article></main></body></html>"""
SEL = EXAMPLE_SOURCES[0]["selectors"]


def test_example_selectors_extract_clean_titles_and_links():
    with respx.mock:
        respx.get("https://example.test/").mock(return_value=httpx.Response(200, text=PAGE))
        with httpx.Client() as c:
            items = fetch_html(c, "https://example.test/", SEL)
    assert [i.title for i in items] == ["Big Buck Bunny", "Sintel"]            # audio-only entry skipped
    assert items[0].torrent_url.endswith("big-buck-bunny.torrent")
    assert items[0].magnet.startswith("magnet:?xt=urn:btih:dd8255")


def test_example_source_scans_into_distinct_movie_releases(db):
    src = Source(name="x", url="https://example.test/", mode="html", selectors=SEL)
    db.add(src)
    db.commit()
    with respx.mock:
        respx.get("https://example.test/").mock(return_value=httpx.Response(200, text=PAGE))
        with httpx.Client() as c:
            assert scan_source(db, src, c, sleep=lambda _: None).startswith("ok: 2 items, 2 new")
    assert sorted(r.title for r in db.scalars(select(Release))) == ["Big Buck Bunny", "Sintel"]


def test_seed_example_sources_once_and_respects_deletion(db):
    added = seed_example_sources(db)
    assert [s.url for s in added] == [EXAMPLE_SOURCES[0]["url"]] and db.get(Setting, "example_sources_seeded")
    assert seed_example_sources(db) == []                                       # idempotent
    db.delete(added[0])
    db.commit()
    assert seed_example_sources(db) == [] and db.scalars(select(Source)).first() is None  # deleted stays deleted


def test_title_regex_and_invalid_regex_message():
    html = '<div class="r"><b>Foo Bar [x]</b><a href="/t.torrent">t</a></div>'
    sel = {"item": ".r", "title": "b", "title_regex": r"^(.*?)\s*\[", "torrent": "a@href"}
    with respx.mock:
        respx.get("https://example.test/").mock(return_value=httpx.Response(200, text=html))
        with httpx.Client() as c:
            assert fetch_html(c, "https://example.test/", sel)[0].title == "Foo Bar"
            with pytest.raises(ValueError, match="invalid selector or title_regex"):
                fetch_html(c, "https://example.test/", {**sel, "title_regex": "("})


@respx.mock
def test_missing_selectors_message_is_actionable(db):
    src = Source(name="x", url="https://example.test/", mode="auto")
    db.add(src)
    db.commit()
    respx.get("https://example.test/").mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.route().mock(return_value=httpx.Response(404))
    with httpx.Client() as c:
        status = scan_source(db, src, c, sleep=lambda _: None)
    assert status == f"error: {NO_SELECTORS_MSG}" and "Open Edit" in status


def test_unrelated_untyped_items_do_not_merge_into_one_release():
    keys = {release_key(parse_title(t)) for t in (
        "ubuntu-24.04.3-desktop-amd64.iso.torrent", "ubuntu-24.04.4-live-server-amd64.iso.torrent")}
    assert len(keys) == 2
    # items that DO carry episode info still group across qualities
    assert release_key(parse_title("Cool.Show.S01E02.720p")) == release_key(parse_title("Cool Show S01E02 1080p"))
