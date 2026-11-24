import httpx
import pytest
import respx

from app.config import settings
from app.scanner import browser_client as bc
from app.scanner.analyze import looks_script_driven
from tests.test_render_sources import EMPTY_SHELL, JS_RENDERED


@pytest.fixture()
def browser(monkeypatch):
    calls = []

    def fake_render(url, *, wait_selector=None, user_agent="", scroll=False, client=None):
        calls.append({"url": url, "wait": wait_selector, "ua": user_agent})
        return bc.RenderedPage(html=JS_RENDERED, final_url="https://films.example/final/", status=200, title="t")
    monkeypatch.setattr(bc, "render", fake_render)
    return calls


@respx.mock
def test_analyze_with_browser_reads_the_rendered_page(api_client, browser):
    plain = respx.get("https://films.example/list").mock(return_value=httpx.Response(200, text=EMPTY_SHELL))
    r = api_client.post("/api/sources/analyze", json={"url": "https://films.example/list", "render": "browser",
                                                      "wait_selector": "li.row", "user_agent": "UA/3"})
    assert r.status_code == 200
    body = r.json()
    assert body["rendered"] is True and body["suggest_browser"] is False
    c = body["candidates"][0]
    assert c["stats"]["items"] == 4 and c["stats"]["with_magnet"] == 4
    assert c["preview"][0]["link"] == "https://films.example/m/1"           # resolved against the FINAL url's host
    assert browser == [{"url": "https://films.example/list", "wait": "li.row", "ua": "UA/3"}]
    assert not plain.called


@respx.mock
def test_static_analysis_of_a_script_driven_page_suggests_the_browser(api_client, browser):
    respx.get("https://films.example/list").mock(return_value=httpx.Response(200, text=EMPTY_SHELL))
    body = api_client.post("/api/sources/analyze", json={"url": "https://films.example/list"}).json()
    assert body["candidates"] == [] and body["suggest_browser"] is True and body["rendered"] is False
    assert browser == []                                                    # nothing used the browser without being asked
    wordy = "<html><body><p>" + "plain words " * 200 + "</p></body></html>"
    respx.get("https://films.example/text").mock(return_value=httpx.Response(200, text=wordy))
    assert api_client.post("/api/sources/analyze", json={"url": "https://films.example/text"}).json()["suggest_browser"] is False


def test_looks_script_driven():
    assert looks_script_driven(EMPTY_SHELL)
    assert looks_script_driven("<html><body><div id='__next'></div><script>1</script>" + "x " * 50 + "</body></html>")
    assert not looks_script_driven("<html><body><p>" + "real content " * 100 + "</p><script>1</script></body></html>")
    assert not looks_script_driven("<html><body><p>tiny</p></body></html>")  # no scripts at all: nothing to render


@pytest.mark.parametrize("exc,status,text", [
    (bc.BrowserUnavailable("Browser rendering is turned off."), 503, "turned off"),
    (bc.BrowserTimeout("did not finish loading"), 504, "timed out"),
    (bc.BrowserBlocked("the site is showing a verification page. Use 'Paste page HTML' instead."), 502, "Paste page HTML"),
    (bc.BrowserError("browser error: crash"), 502, "crash"),
])
def test_browser_failures_become_clear_http_errors(api_client, monkeypatch, exc, status, text):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(bc, "render", boom)
    r = api_client.post("/api/sources/analyze", json={"url": "https://films.example/list", "render": "browser"})
    assert r.status_code == status and text in r.json()["detail"]


def test_the_same_site_rule_for_detail_pages_still_applies_when_rendering(api_client, browser):
    r = api_client.post("/api/sources/analyze", json={"kind": "detail", "url": "http://192.168.0.1/admin",
                                                      "site_url": "https://films.example/list", "render": "browser"})
    assert r.status_code == 400 and "same site" in r.json()["detail"] and browser == []


def test_pasted_html_never_uses_the_browser(api_client, browser):
    r = api_client.post("/api/sources/analyze", json={"html": JS_RENDERED, "render": "browser"})
    assert r.status_code == 200 and r.json()["rendered"] is False and r.json()["candidates"] and browser == []


def test_settings_endpoint_reports_whether_the_browser_is_enabled(api_client, monkeypatch):
    monkeypatch.setattr(settings, "browser_enabled", True)
    assert api_client.get("/api/settings").json()["browser_enabled"] is True
    monkeypatch.setattr(settings, "browser_enabled", False)
    assert api_client.get("/api/settings").json()["browser_enabled"] is False
