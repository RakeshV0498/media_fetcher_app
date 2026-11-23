import httpx
import respx
from sqlalchemy import select

from app.models import Release, Source, Variant
from app.scanner.discovery import discover_feed
from app.scanner.feed import fetch_feed
from app.scanner.html import fetch_html
from app.scanner.runner import scan_source

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Cool Show S01E02 1080p WEB x265</title><link>http://x/1</link>
<description>Size: 1.4 GB Seeders: 120 Leechers: 4
magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA</description></item>
<item><title>Cool Show S01E02 720p HDTV x264</title><link>http://x/2</link>
<enclosure url="http://x/2.torrent" type="application/x-bittorrent" length="500000000"/></item>
</channel></rss>"""

HTML = """<html><body><table>
<tr class="r"><td><a class="t" href="/d/1">One Piece - 1056 (1080p)</a></td>
<td class="s">1.2 GB</td><td class="se">88</td><td><a class="m" href="magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB">m</a></td></tr>
<tr class="r"><td><a class="t" href="/d/2">One Piece - 1056 (720p)</a></td>
<td class="s">400 MB</td><td class="se">12</td><td><a class="m" href="magnet:?xt=urn:btih:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC">m</a></td></tr>
</table></body></html>"""

SEL = {"item": "tr.r", "title": "a.t", "link": "a.t@href", "size": ".s",
       "seeders": ".se", "magnet": "a.m@href"}


@respx.mock
def test_discovery_link_tag():
    respx.get("http://site/").mock(return_value=httpx.Response(
        200, text='<html><head><link rel="alternate" type="application/rss+xml" href="/f.xml"></head></html>'))
    respx.get("http://site/f.xml").mock(return_value=httpx.Response(200, text=RSS))
    with httpx.Client() as c:
        assert discover_feed(c, "http://site/") == "http://site/f.xml"


@respx.mock
def test_discovery_common_path_and_none():
    respx.get("http://site/").mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get("http://site/feed").mock(return_value=httpx.Response(404))
    respx.get("http://site/rss").mock(return_value=httpx.Response(200, text=RSS))
    respx.route().mock(return_value=httpx.Response(404))
    with httpx.Client() as c:
        assert discover_feed(c, "http://site/") == "http://site/rss"
    respx.get("http://site/rss").mock(return_value=httpx.Response(404))
    with httpx.Client() as c:
        assert discover_feed(c, "http://site/") is None


@respx.mock
def test_feed_adapter():
    respx.get("http://site/f").mock(return_value=httpx.Response(200, text=RSS))
    with httpx.Client() as c:
        a, b = fetch_feed(c, "http://site/f")
    assert a.seeders == 120 and a.leechers == 4 and a.magnet.startswith("magnet:")
    assert "1.4 GB" in a.size_text
    assert b.torrent_url == "http://x/2.torrent" and b.size_text == "500000000"


@respx.mock
def test_html_adapter():
    respx.get("http://site/list").mock(return_value=httpx.Response(200, text=HTML))
    with httpx.Client() as c:
        items = fetch_html(c, "http://site/list", SEL)
    assert [i.seeders for i in items] == [88, 12]
    assert items[0].link == "http://site/d/1" and items[0].magnet.startswith("magnet:")


@respx.mock
def test_runner_groups_variants_and_refreshes_seeders(db):
    src = Source(name="s", url="http://site/list", mode="html", selectors=SEL)
    db.add(src)
    db.commit()
    route = respx.get("http://site/list").mock(return_value=httpx.Response(200, text=HTML))
    with httpx.Client() as c:
        assert scan_source(db, src, c, sleep=lambda _: None).startswith("ok: 2 items, 2 new")
        rels = db.scalars(select(Release)).all()
        assert len(rels) == 1 and len(rels[0].variants) == 2
        assert rels[0].suggested_tag_id is not None
        route.mock(return_value=httpx.Response(200, text=HTML.replace(">88<", ">99<")))
        assert "0 new" in scan_source(db, src, c, sleep=lambda _: None)
    seeds = sorted(v.seeders for v in db.scalars(select(Variant)))
    assert seeds == [12, 99]


@respx.mock
def test_runner_auto_uses_feed_else_records_error(db):
    src = Source(name="s", url="http://site/", mode="auto")
    db.add(src)
    db.commit()
    respx.get("http://site/").mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get("http://site/feed").mock(return_value=httpx.Response(200, text=RSS))
    with httpx.Client() as c:
        assert scan_source(db, src, c, sleep=lambda _: None).startswith("ok: 2 items")
    assert src.feed_url == "http://site/feed"
    bad = Source(name="b", url="http://site/", mode="html", selectors={})
    db.add(bad)
    db.commit()
    with httpx.Client() as c:
        assert scan_source(db, bad, c, sleep=lambda _: None).startswith("error:")
