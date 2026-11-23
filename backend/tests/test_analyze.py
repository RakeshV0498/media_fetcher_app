import httpx
import pytest
import respx

from app.scanner.analyze import analyze_detail, analyze_listing
from app.scanner.html import parse_html

BASE = "https://x.test/"
MAG = "magnet:?xt=urn:btih:"


def best(html):
    cands, warns = analyze_listing(html, BASE)
    assert cands, warns
    return cands[0]


def titles(c, html):
    return [i.title for i in parse_html(html, BASE, c.selectors)]


NAV = '<nav class="top"><ul><li><a href="/a">Home page</a></li><li><a href="/b">Browse all</a></li><li><a href="/c">Upload one</a></li></ul></nav>'

TABLE = NAV + """<table class="list"><thead><tr><th>Name</th><th>Size</th><th>SE</th><th>LE</th><th>DL</th></tr></thead><tbody>
<tr><td><a href="/t/1">Movie One (2024) 1080p x265</a></td><td>1.4 GB</td><td>120</td><td>4</td><td><a href="%s1">m</a></td></tr>
<tr><td><a href="/t/2">Movie Two (2023) 720p x264</a></td><td>700 MB</td><td>30</td><td>1</td><td><a href="%s2">m</a></td></tr>
<tr><td><a href="/t/3">Movie Three (2022) 2160p x265</a></td><td>9 GB</td><td>5</td><td>0</td><td><a href="%s3">m</a></td></tr>
<tr><td><a href="/t/4">Movie Four (2021) 1080p x264</a></td><td>2 GB</td><td>7</td><td>2</td><td><a href="%s4">m</a></td></tr></tbody></table>""" % (MAG, MAG, MAG, MAG)

CARDS = NAV + "".join(f"""<div class="results"><div class="card"><h3 class="name"><a href="/d/{i}">Show Title S01E0{i} 1080p WEB</a></h3>
<span class="meta-size">{i}.2 GB</span><span class="seeds">{i * 11}</span><span class="leech">{i}</span>
<a class="get" href="/dl/{i}.torrent">Download</a></div></div>""" for i in range(1, 5))

LIST_ITEMS = NAV + "<ul class='feed'>" + "".join(f"""<li class="row"><div class="n"><a href="/x/{i}">Another Movie {i} (202{i}) 1080p</a></div>
<div class="s">{i}.5 GB</div><a href="{MAG}{i}">magnet</a></li>""" for i in range(1, 5)) + "</ul>"

TWO_LEVEL = NAV + "".join(f"""<div class="entry"><a class="t" href="/m/{i}.html">Listing Film {i} (2024) HD</a><span>2024</span></div>""" for i in range(1, 6))

TEXT_THEN_LINKS = "<ul>" + "".join(
    f'<li><p>Open Film {n} <a href="https://x.test/t/{n}.torrent">(torrent file)</a> <a href="{MAG}{n}">(magnet link)</a></p></li>'
    for n in ("One", "Two", "Three")) + "</ul>"


def test_table_layout_uses_header_columns_and_skips_nav_and_header_row():
    c = best(TABLE)
    assert c.selectors["item"].startswith("tr")
    assert c.selectors["size"] == "td:nth-child(2)" and c.selectors["seeders"] == "td:nth-child(3)"
    assert c.selectors["leechers"] == "td:nth-child(4)" and "magnet" in c.selectors
    assert c.stats["items"] == 4 and c.stats["with_magnet"] == 4 and c.stats["with_seeders"] == 4
    assert titles(c, TABLE)[0] == "Movie One (2024) 1080p x265" and not c.two_level
    assert c.preview[0]["seeders"] == 120 and c.preview[0]["size"] == "1.4 GB"


def test_div_cards_use_class_hints_and_direct_torrent_links():
    c = best(CARDS)
    s = c.selectors
    assert s["title"].startswith("h3") and s["torrent"].endswith("@href") and ".torrent" in s["torrent"]
    assert s["seeders"].endswith("seeds") and s["leechers"].endswith("leech") and "size" in s
    assert c.stats["items"] == 4 and c.stats["with_torrent"] == 4 and c.preview[1]["seeders"] == 22


def test_plain_list_items_with_magnets_and_size_found_by_pattern():
    c = best(LIST_ITEMS)
    assert c.selectors["item"].endswith("li.row") and c.stats["with_magnet"] == 4
    assert c.preview[0]["size"] == "1.5 GB" and c.preview[0]["title"].startswith("Another Movie 1")


def test_listing_without_download_links_is_flagged_two_level():
    c = best(TWO_LEVEL)
    assert c.two_level and c.stats["with_magnet"] == 0 and c.stats["with_link"] == 5
    assert any("own page" in n for n in c.notes)
    assert c.preview[0]["link"] == "https://x.test/m/1.html"


def test_title_held_in_text_before_the_links_gets_a_title_regex():
    c = best(TEXT_THEN_LINKS)
    assert "title_regex" in c.selectors
    assert titles(c, TEXT_THEN_LINKS) == ["Open Film One", "Open Film Two", "Open Film Three"]
    assert c.stats["with_magnet"] == 3 and c.stats["with_torrent"] == 3


def test_navigation_menus_are_not_mistaken_for_the_listing():
    cands, warns = analyze_listing(NAV + "<p>nothing else</p>", BASE)
    assert cands == [] and "JavaScript" in warns[0]


def test_javascript_only_page_gets_a_helpful_warning():
    cands, warns = analyze_listing("<html><body><div id='app'></div><script src='/app.js'></script></body></html>", BASE)
    assert cands == [] and "JavaScript" in warns[0] and "Paste page HTML" in warns[0]


DETAIL_WRAPPED = "<html><body><h1>Sample Film</h1>" + "".join(f"""<div class="ver"><span class="name">Sample Film (2024) {q} x26{i}</span>
<span class="size">{sz}</span><span class="seeds">{se}</span><a class="mag" href="{MAG}{i}">M</a><a class="tor" href="/f/{i}.torrent">T</a></div>"""
    for i, (q, sz, se) in enumerate([("2160p", "9.1 GB", 40), ("1080p", "2.4 GB", 310), ("720p", "900 MB", 12)], start=1)) + "</body></html>"

DETAIL_FLAT = ("<html><body><div class='post'>" + "".join(
    f'Title {i} 1080p<br><a href="/x/{i}.torrent">file {i}</a><a href="{MAG}{i}">MAGNET</a><br>' for i in range(1, 4))
    + "</div></body></html>")


def test_detail_page_versions_are_separated_with_quality_size_seeders():
    cands, warns = analyze_detail(DETAIL_WRAPPED, BASE)
    assert warns == [] and cands
    c = cands[0]
    assert c.stats["items"] == 3 and c.stats["with_magnet"] == 3 and c.stats["with_torrent"] == 3
    assert c.stats["with_size"] == 3 and c.stats["with_seeders"] == 3
    got = parse_html(DETAIL_WRAPPED, BASE, c.selectors)
    assert [i.title for i in got] == ["Sample Film (2024) 2160p x261", "Sample Film (2024) 1080p x262", "Sample Film (2024) 720p x263"]
    assert [i.seeders for i in got] == [40, 310, 12] and got[1].size_text == "2.4 GB"


def test_detail_page_without_wrapping_or_links_explains_itself():
    cands, warns = analyze_detail(DETAIL_FLAT, BASE)
    assert cands == [] and "can't be separated" in warns[0]
    cands, warns = analyze_detail("<html><body><p>nothing</p></body></html>", BASE)
    assert cands == [] and "No magnet or .torrent links" in warns[0]


# ---------------------------------------------------------------- API
@respx.mock
def test_analyze_api_fetches_a_url_and_returns_candidates(api_client):
    respx.get("https://x.test/list").mock(return_value=httpx.Response(200, text=TABLE))
    r = api_client.post("/api/sources/analyze", json={"url": "https://x.test/list"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0]["selectors"]["item"].startswith("tr") and body["candidates"][0]["stats"]["items"] == 4


def test_analyze_api_accepts_pasted_html_and_detail_kind(api_client):
    r = api_client.post("/api/sources/analyze", json={"html": DETAIL_WRAPPED, "kind": "detail"})
    assert r.status_code == 200 and r.json()["candidates"][0]["count"] == 3
    r = api_client.post("/api/sources/analyze", json={"html": "<html></html>"})
    assert r.status_code == 200 and r.json()["candidates"] == [] and r.json()["warnings"]


@respx.mock
def test_analyze_api_errors_are_actionable_and_guarded(api_client):
    assert api_client.post("/api/sources/analyze", json={}).status_code == 422
    assert api_client.post("/api/sources/analyze", json={"url": "file:///etc/passwd"}).status_code == 422
    assert api_client.post("/api/sources/analyze", json={"url": "https://x.test/", "kind": "weird"}).status_code == 422
    respx.get("https://blocked.test/").mock(return_value=httpx.Response(403))
    r = api_client.post("/api/sources/analyze", json={"url": "https://blocked.test/"})
    assert r.status_code == 502 and "Paste page HTML" in r.json()["detail"]
    respx.get("https://down.test/").mock(side_effect=httpx.ConnectError("refused"))
    assert api_client.post("/api/sources/analyze", json={"url": "https://down.test/"}).status_code == 502
    route = respx.route().mock(return_value=httpx.Response(200, text="<html></html>"))
    r = api_client.post("/api/sources/analyze", json={"url": "http://192.168.0.1/admin", "kind": "detail",
                                                      "site_url": "https://x.test/list"})
    assert r.status_code == 400 and "same site" in r.json()["detail"] and not route.called
    big = "x" * 4_100_000
    assert api_client.post("/api/sources/analyze", json={"html": big}).status_code == 413


def test_analyze_requires_login():
    from fastapi.testclient import TestClient

    from app.main import app
    assert TestClient(app).post("/api/sources/analyze", json={"html": "<p>"}).status_code == 401


def test_a_short_two_entry_list_is_found_when_nothing_bigger_exists():
    html = ('<div class="entry"><a class="title" href="/m/1.html">Sample Film (2024) HD</a></div>'
            '<div class="entry"><a class="title" href="/m/2.html">Second Film (2023) HD</a></div>')
    c = best(html)
    assert c.count == 2 and c.two_level
    # ...but a 2-item menu is still not mistaken for a listing when the page has a real one
    assert best(NAV + TABLE).selectors["item"].startswith("tr")
