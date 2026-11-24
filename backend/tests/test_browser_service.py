import asyncio
import contextlib
import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from playwright.async_api import TimeoutError as PwTimeout  # noqa: E402

from browsersvc import guard, main as svc  # noqa: E402

PUBLIC = "https://example.com/list"


# ---------------- a minimal fake of the Playwright objects the service touches ----------------
class FakePage:
    def __init__(self, behaviour):
        self.b, self.url, self.calls = behaviour, behaviour.get("final_url", PUBLIC), []
        self.mouse = type("M", (), {"wheel": staticmethod(self._noop)})()

    async def _noop(self, *a, **k):
        self.calls.append("wheel")

    async def route(self, pattern, handler):
        self.handler = handler

    async def goto(self, url, **k):
        if self.b.get("goto_timeout"):
            raise PwTimeout("Timeout 30000ms exceeded")
        return type("R", (), {"status": self.b.get("status", 200)})()

    async def wait_for_selector(self, sel, **k):
        self.calls.append(("wait_for_selector", sel))

    async def wait_for_load_state(self, *a, **k):
        if self.b.get("never_idle"):
            raise PwTimeout("networkidle")

    async def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))

    async def content(self):
        return self.b.get("html", "<html><body><ul><li>x</li></ul></body></html>")

    async def title(self):
        return self.b.get("title", "A list")


class FakeBrowser:
    def __init__(self, behaviour):
        self.b, self.closed = behaviour, False

    async def new_context(self, **kw):
        self.b["context_kwargs"] = kw
        return type("C", (), {"new_page": lambda s: self._page()})()

    async def _page(self):
        self.page = FakePage(self.b)
        self.b["page"] = self.page
        return self.page

    async def close(self):
        self.closed = True
        self.b["closed"] = True


def fake_factory(behaviour):
    @contextlib.asynccontextmanager
    async def factory():
        async def launch(**kw):
            behaviour["launch_kwargs"] = kw
            return FakeBrowser(behaviour)
        yield type("PW", (), {"chromium": type("Ch", (), {"launch": staticmethod(launch)})()})()
    return factory


def req(**kw):
    return svc.RenderIn(url=kw.pop("url", PUBLIC), **kw)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BROWSER_TOKEN", "tok")
    monkeypatch.delenv("ALLOW_PRIVATE", raising=False)
    monkeypatch.setattr(guard, "RESOLVE", lambda host, port, type=0: [(2, 1, 6, "", ("93.184.216.34", port))])


def run(coro):
    return asyncio.run(coro)


# ---------------- render_page ----------------
def test_render_returns_html_with_honest_settings_and_closes_the_browser():
    b = {}
    out = run(svc.render_page(req(user_agent="MediaFetcher/1", wait_selector="li"), fake_factory(b)))
    assert out["status"] == 200 and out["title"] == "A list" and "<li>x</li>" in out["html"] and out["blocked"] is None
    assert b["context_kwargs"]["user_agent"] == "MediaFetcher/1"          # the configured UA, no spoofing
    assert b["launch_kwargs"]["headless"] is True and "--no-sandbox" in b["launch_kwargs"]["args"]
    assert ("wait_for_selector", "li") in b["page"].calls and b["closed"] is True


def test_render_closes_the_browser_even_when_the_page_times_out_and_maps_to_504():
    b = {"goto_timeout": True}
    with pytest.raises(HTTPException) as e:
        run(svc.render_page(req(), fake_factory(b)))
    assert e.value.status_code == 504 and "did not finish loading" in e.value.detail and b["closed"] is True


def test_chatty_pages_that_never_go_idle_are_still_taken():
    out = run(svc.render_page(req(), fake_factory({"never_idle": True})))
    assert "<li>x</li>" in out["html"]


def test_scroll_and_wait_options_are_honoured():
    b = {}
    run(svc.render_page(req(scroll=True, wait_ms=500), fake_factory(b)))
    assert b["page"].calls.count("wheel") == 6 and ("wait", 500) in b["page"].calls


def test_a_redirect_to_an_internal_address_is_refused(monkeypatch):
    from browsersvc.guard import UrlRefused
    b = {"final_url": "http://192.168.0.1/admin"}

    def resolve(host, port, type=0):
        ip = "192.168.0.1" if host == "192.168.0.1" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, port))]
    monkeypatch.setattr(guard, "RESOLVE", resolve)
    with pytest.raises(UrlRefused):
        run(svc.render_page(req(), fake_factory(b)))
    assert b["closed"] is True


def test_oversized_pages_are_rejected():
    with pytest.raises(HTTPException) as e:
        run(svc.render_page(req(), fake_factory({"html": "x" * (svc.MAX_HTML + 1)})))
    assert e.value.status_code == 413


def test_bot_check_pages_are_flagged_blocked():
    out = run(svc.render_page(req(), fake_factory({"title": "Just a moment...", "status": 403})))
    assert out["blocked"] and "verification" in out["blocked"]


def test_sub_requests_for_images_and_internal_hosts_are_aborted(monkeypatch):
    b, decisions = {}, []

    class Route:
        def __init__(self, url, rtype):
            self.request = type("Rq", (), {"url": url, "resource_type": rtype})()

        async def abort(self):
            decisions.append("abort")

        async def continue_(self):
            decisions.append("continue")

    monkeypatch.setattr(guard, "RESOLVE", lambda host, port, type=0: [
        (2, 1, 6, "", ("10.0.0.7" if host == "intranet.test" else "93.184.216.34", port))])
    run(svc.render_page(req(), fake_factory(b)))
    handler = b["page"].handler
    for url, rtype in [("https://cdn.example.com/a.png", "image"), ("https://cdn.example.com/app.js", "script"),
                       ("http://intranet.test/secret", "xhr"), ("https://cdn.example.com/f.woff", "font")]:
        run(handler(Route(url, rtype)))
    assert decisions == ["abort", "continue", "abort", "abort"]


# ---------------- HTTP surface ----------------
def test_endpoints_require_the_token_and_fail_closed(monkeypatch):
    c = TestClient(svc.app)
    assert c.get("/health").status_code == 401
    assert c.get("/health", headers={"X-Browser-Token": "wrong"}).status_code == 401
    assert c.get("/health", headers={"X-Browser-Token": "tok"}).json() == {"ok": True}
    monkeypatch.delenv("BROWSER_TOKEN")
    assert c.get("/health", headers={"X-Browser-Token": ""}).status_code == 503


def test_render_endpoint_refuses_unsafe_urls_and_serialises_renders(monkeypatch):
    h = {"X-Browser-Token": "tok"}
    c = TestClient(svc.app)
    assert c.post("/render", headers=h, json={"url": "file:///etc/passwd"}).status_code == 400
    assert c.post("/render", headers=h, json={"url": "http://user:pw@example.com/"}).status_code == 400
    assert c.post("/render", headers=h, json={"url": PUBLIC, "timeout_s": 1}).status_code == 422   # below the minimum
    active, peak = 0, 0

    async def slow(req, factory=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return {"html": "<p>x</p>", "final_url": req.url, "status": 200, "title": "t", "blocked": None}
    monkeypatch.setattr(svc, "render_page", slow)

    async def go():
        await asyncio.gather(*(svc.render(req()) for _ in range(4)))
    run(go())
    assert peak == 1                                                       # never more than one browser at a time


# ---------------- real Chromium (skipped where Chromium is not installed) ----------------
def _chromium() -> str | None:
    cands = [os.environ.get("CHROMIUM_PATH", "")] + sorted(
        str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome"))
    return next((c for c in cands if c and Path(c).exists()), None)


JS_PAGE = """<html><head><title>JS list</title></head><body><ul id="list"></ul><script>
setTimeout(() => { const films = [["Alpha Film (2024) 1080p",1],["Beta Film (2023) 720p",2],["Gamma Film (2022) 2160p",3],["Delta Film (2021) 1080p",4]];
 for (const [t,i] of films) { const li = document.createElement('li'); li.className = 'row';
  li.innerHTML = '<a href="/m/'+i+'">'+t+'</a> <a href="magnet:?xt=urn:btih:'+String(i).repeat(40).slice(0,40)+'">magnet</a>';
  document.getElementById('list').appendChild(li); } }, 300);
</script></body></html>"""


@pytest.mark.browser
@pytest.mark.skipif(_chromium() is None, reason="Chromium is not installed here")
def test_real_chromium_renders_javascript_lists_that_plain_http_cannot_see(tmp_path, monkeypatch):
    import httpx

    from app.scanner.analyze import analyze_listing
    (tmp_path / "index.html").write_text(JS_PAGE)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    monkeypatch.setenv("ALLOW_PRIVATE", "1")                               # the test page is on loopback
    monkeypatch.setattr(svc, "CHROMIUM", _chromium())
    try:
        static_html = httpx.get(url).text
        assert "<li" not in static_html and analyze_listing(static_html, url)[0] == []   # plain HTTP sees nothing
        with TestClient(svc.app) as c:
            assert c.get("/selftest", headers={"X-Browser-Token": "tok"}).json()["ok"] is True
            r = c.post("/render", headers={"X-Browser-Token": "tok"}, json={"url": url, "wait_selector": "li.row"})
        assert r.status_code == 200, r.text
        cands, warnings = analyze_listing(r.json()["html"], url)
        assert cands and cands[0].stats["items"] == 4 and cands[0].stats["with_magnet"] == 4
        assert cands[0].preview[0]["title"] == "Alpha Film (2024) 1080p"
    finally:
        srv.shutdown()
