import socket

import httpx
import pytest
import respx

from app.config import settings
from app.scanner import browser_client as bc
from browsersvc.guard import UrlRefused, check_url, detect_block

BASE = "http://browser:8100"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "browser_enabled", True)
    monkeypatch.setattr(settings, "browser_url", BASE)
    monkeypatch.setattr(settings, "browser_token", "tok")
    monkeypatch.setattr(settings, "browser_timeout_s", 20)


def resolver(ip):
    return lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


# ---------------- URL guard ----------------
@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert check_url("https://example.com/x", resolve=resolver(ip)) == "https://example.com/x"


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.0.1", "172.16.4.4", "169.254.169.254", "100.64.1.2",
                                "0.0.0.0", "::1", "fe80::1", "fd00::1"])
def test_private_loopback_and_link_local_addresses_are_refused(ip):
    with pytest.raises(UrlRefused, match="private|internal"):
        check_url("http://innocent-looking.example/", resolve=resolver(ip))


@pytest.mark.parametrize("url,msg", [
    ("file:///etc/passwd", "http and https"), ("ftp://example.com/", "http and https"),
    ("javascript:alert(1)", "http and https"), ("http://user:pw@example.com/", "credentials"),
    ("http:///nohost", "no host"),
])
def test_unsafe_url_shapes_are_refused(url, msg):
    with pytest.raises(UrlRefused, match=msg):
        check_url(url, resolve=resolver("93.184.216.34"))


def test_unresolvable_host_and_allow_private_switch():
    def boom(*a, **k):
        raise socket.gaierror("nope")
    with pytest.raises(UrlRefused, match="cannot resolve"):
        check_url("http://nonexistent.invalid/", resolve=boom)
    assert check_url("http://192.168.0.5/", allow_private=True) == "http://192.168.0.5/"


def test_every_resolved_address_is_checked_not_just_the_first():
    def mixed(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.9", port))]
    with pytest.raises(UrlRefused):
        check_url("http://rebind.example/", resolve=mixed)


# ---------------- challenge detection ----------------
@pytest.mark.parametrize("status,title,html,expect", [
    (200, "Just a moment...", "<html></html>", True),
    (200, "Attention Required! | Cloudflare", "", True),
    (403, "x", "<script src='/cdn-cgi/challenge-platform/h/b'></script>", True),
    (503, "Site", "enable javascript and cookies to continue", True),
    (403, "Forbidden", "<html>nope</html>", True),
    (429, "Too many", "", True),
    (200, "Open Films", "<html><body>normal page</body></html>", False),
    (404, "Not found", "<html></html>", False),
])
def test_detect_block(status, title, html, expect):
    assert bool(detect_block(status, title, html)) is expect


# ---------------- controller client ----------------
def ok(**kw):
    return httpx.Response(200, json={"html": "<html>rendered</html>", "final_url": "https://x.test/p", "status": 200,
                                     "title": "T", "blocked": None, **kw})


@respx.mock
def test_render_returns_page_and_sends_token_ua_and_selector():
    route = respx.post(f"{BASE}/render").mock(return_value=ok())
    p = bc.render("https://x.test/p", wait_selector="li.row", user_agent="UA/1")
    assert (p.html, p.final_url, p.status, p.title) == ("<html>rendered</html>", "https://x.test/p", 200, "T")
    req = route.calls[0].request
    assert req.headers["X-Browser-Token"] == "tok"
    body = req.content.decode().replace(" ", "")
    assert '"wait_selector":"li.row"' in body and '"user_agent":"UA/1"' in body and '"timeout_s":20' in body


def test_render_refuses_when_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "browser_enabled", False)
    with pytest.raises(bc.BrowserUnavailable, match="turned off"):
        bc.render("https://x.test/")


@respx.mock
def test_render_error_mapping():
    respx.post(f"{BASE}/render").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(bc.BrowserUnavailable, match="--profile browser"):
        bc.render("https://x.test/")
    respx.post(f"{BASE}/render").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(bc.BrowserTimeout):
        bc.render("https://x.test/")
    respx.post(f"{BASE}/render").mock(return_value=httpx.Response(401, json={"detail": "bad token"}))
    with pytest.raises(bc.BrowserUnavailable, match="token"):
        bc.render("https://x.test/")
    respx.post(f"{BASE}/render").mock(return_value=httpx.Response(503, json={"detail": "BROWSER_TOKEN is not configured"}))
    with pytest.raises(bc.BrowserUnavailable, match="token"):
        bc.render("https://x.test/")
    respx.post(f"{BASE}/render").mock(return_value=httpx.Response(504, json={"detail": "did not finish loading in 20s"}))
    with pytest.raises(bc.BrowserTimeout, match="did not finish"):
        bc.render("https://x.test/")
    respx.post(f"{BASE}/render").mock(return_value=httpx.Response(400, json={"detail": "resolves to a private address"}))
    with pytest.raises(bc.BrowserError, match="private address"):
        bc.render("https://x.test/")
    respx.post(f"{BASE}/render").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(bc.BrowserError, match="500"):
        bc.render("https://x.test/")


@respx.mock
def test_blocked_pages_are_reported_not_worked_around():
    respx.post(f"{BASE}/render").mock(return_value=ok(blocked='the site is showing a verification page ("Just a moment")'))
    with pytest.raises(bc.BrowserBlocked, match="Paste page HTML"):
        bc.render("https://x.test/")


# ---------------- settings integration ----------------
def test_browser_settings_are_in_the_registry_and_token_is_secret(api_client):
    f = {x["key"]: x for x in api_client.get("/api/app-settings").json()["fields"]}
    assert f["browser_enabled"]["group"] == "integrations" and f["browser_enabled"]["value"] is True
    assert f["browser_token"]["kind"] == "secret" and "value" not in f["browser_token"]
    assert f["browser_timeout_s"]["kind"] == "int"
    assert api_client.put("/api/app-settings", json={"values": {"browser_timeout_s": 500}}).status_code == 422   # max 120


@respx.mock
def test_browser_test_button(api_client, monkeypatch):
    respx.get(f"{BASE}/selftest").mock(return_value=httpx.Response(200, json={"ok": True, "chromium": "153.0"}))
    r = api_client.post("/api/app-settings/test/browser").json()
    assert r["ok"] and "153.0" in r["message"]
    respx.get(f"{BASE}/selftest").mock(return_value=httpx.Response(401))
    assert "token" in api_client.post("/api/app-settings/test/browser").json()["message"]
    respx.get(f"{BASE}/selftest").mock(side_effect=httpx.ConnectError("refused"))
    assert "--profile browser" in api_client.post("/api/app-settings/test/browser").json()["message"]
    respx.get(f"{BASE}/selftest").mock(return_value=httpx.Response(502, json={"detail": "browser failed to start: x"}))
    assert "failed to start" in api_client.post("/api/app-settings/test/browser").json()["message"]
    monkeypatch.setattr(settings, "browser_enabled", False)
    assert "switched off" in api_client.post("/api/app-settings/test/browser").json()["message"]
