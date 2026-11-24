import httpx
import pytest
import respx
from sqlalchemy import select

from app.config import settings
from app.models import Release, Source, Variant
from app.scanner import browser_client as bc
from app.scanner.details import load_versions
from app.scanner.runner import scan_source

JS_RENDERED = """<html><body><ul>""" + "".join(
    f'<li class="row"><a href="/m/{i}">Rendered Film {i} (202{i}) 1080p</a> <a href="magnet:?xt=urn:btih:{str(i) * 40}">m</a></li>'
    for i in range(1, 5)) + "</ul></body></html>"
EMPTY_SHELL = "<html><body><div id='app'></div><script src='/app.js'></script></body></html>"
SEL = {"item": "li.row", "title": "a:first-child", "magnet": "a[href^='magnet:']@href", "link": "a:first-child@href"}


@pytest.fixture()
def calls(monkeypatch):
    seen = []

    def fake_render(url, *, wait_selector=None, user_agent="", scroll=False, client=None):
        seen.append({"url": url, "wait": wait_selector, "ua": user_agent})
        return bc.RenderedPage(html=JS_RENDERED, final_url="https://films.example/list/", status=200, title="t")
    monkeypatch.setattr(bc, "render", fake_render)
    return seen


@respx.mock
def test_browser_source_scans_the_rendered_page_and_resolves_links_against_the_final_url(db, calls):
    src = Source(name="js", url="https://films.example/list", mode="html", selectors=SEL, render="browser",
                 wait_selector="li.row", user_agent="UA/2")
    db.add(src)
    db.commit()
    plain = respx.get("https://films.example/list").mock(return_value=httpx.Response(200, text=EMPTY_SHELL))
    with httpx.Client() as c:
        assert scan_source(db, src, c, sleep=lambda _: None) == "ok: 4 items, 4 new"
    assert calls == [{"url": "https://films.example/list", "wait": "li.row", "ua": "UA/2"}]
    assert not plain.called                                                 # plain HTTP was not used for the page
    assert sorted(r.title for r in db.scalars(select(Release))) == [f"Rendered Film {i}" for i in range(1, 5)]
    assert all(v.link.startswith("https://films.example/m/") for v in db.scalars(select(Variant)))


@respx.mock
def test_static_source_never_touches_the_browser(db, calls):
    src = Source(name="plain", url="https://films.example/list", mode="html", selectors=SEL)
    db.add(src)
    db.commit()
    respx.get("https://films.example/list").mock(return_value=httpx.Response(200, text=JS_RENDERED))
    with httpx.Client() as c:
        assert scan_source(db, src, c, sleep=lambda _: None).startswith("ok: 4 items")
    assert calls == []
    assert src.render == "static"


def test_browser_problems_are_recorded_as_readable_scan_errors(db, monkeypatch):
    src = Source(name="js", url="https://films.example/list", mode="html", selectors=SEL, render="browser")
    db.add(src)
    db.commit()
    for exc, text in [(bc.BrowserBlocked("the site is showing a verification page. Open the page in your own browser and "
                                         "use 'Paste page HTML' instead."), "verification page"),
                      (bc.BrowserUnavailable("Browser rendering is turned off."), "turned off"),
                      (bc.BrowserTimeout("did not finish loading"), "did not finish")]:
        def boom(*a, **k):
            raise exc
        monkeypatch.setattr(bc, "render", boom)
        with httpx.Client() as c:
            status = scan_source(db, src, c, sleep=lambda _: None)
        assert status.startswith("error:") and text in status and src.last_status == status


def test_missing_selectors_fail_before_any_browser_render(db, calls):
    src = Source(name="js", url="https://films.example/list", mode="html", selectors={}, render="browser")
    db.add(src)
    db.commit()
    with httpx.Client() as c:
        assert "no HTML selectors" in scan_source(db, src, c, sleep=lambda _: None)
    assert calls == []                                                      # no browser time wasted


DETAIL_JS = ("<html><body>" + "".join(
    f'<div class="ver"><span class="n">Rendered Film (2024) {q} x264</span><a class="mag" href="magnet:?xt=urn:btih:{str(i) * 40}">m</a></div>'
    for i, q in enumerate(["2160p", "1080p", "720p"], start=1)) + "</body></html>")


def test_load_versions_follows_the_sources_render_setting(db, monkeypatch):
    seen = []

    def fake_render(url, *, wait_selector=None, user_agent="", scroll=False, client=None):
        seen.append((url, wait_selector))
        return bc.RenderedPage(html=DETAIL_JS, final_url=url, status=200, title="d")
    monkeypatch.setattr(bc, "render", fake_render)
    src = Source(name="js2", url="https://films.example/list", mode="html", render="browser", wait_selector="div.ver",
                 selectors={"item": "div.entry", "title": "a", "link": "a@href",
                            "detail": {"item": "div.ver", "title": ".n", "magnet": "a.mag@href"}})
    db.add(src)
    db.flush()
    rel = Release(release_key="rf", title="Rendered Film", kind="movie", detail_url="https://films.example/m/1",
                  detail_source_id=src.id)
    db.add(rel)
    db.commit()
    with httpx.Client() as c:
        assert load_versions(db, rel, c) == 3
    assert seen == [("https://films.example/m/1", "div.ver")]
    assert sorted(v.quality for v in rel.variants) == ["1080p", "2160p", "720p"]


def test_sources_api_accepts_render_and_wait_selector(api_client):
    body = {"name": "j", "url": "https://x.test/", "mode": "html", "selectors": SEL, "render": "browser",
            "wait_selector": "li.row"}
    r = api_client.post("/api/sources", json=body)
    assert r.status_code == 201 and r.json()["render"] == "browser" and r.json()["wait_selector"] == "li.row"
    sid = r.json()["id"]
    assert api_client.put(f"/api/sources/{sid}", json={**body, "render": "static", "wait_selector": None}).json()["render"] == "static"
    assert api_client.post("/api/sources", json={**body, "render": "chrome"}).status_code == 422
    assert api_client.post("/api/sources", json={k: v for k, v in body.items() if k != "render"}).json()["render"] == "static"
