import pytest
from fastapi.testclient import TestClient

from app import auth
from app.api import auth as auth_api
from app.config import settings
from app.download.gate import check_gate
from app.main import app


@pytest.mark.parametrize("enabled,vpn,mock,allowed", [
    (False, False, True, True), (False, True, True, True),   # mock never blocked
    (False, False, False, False), (False, True, False, False),  # flag off blocks
    (True, False, False, False),                               # VPN fail blocks
    (True, True, False, True),
])
def test_gate_truth_table(enabled, vpn, mock, allowed):
    r = check_gate(enabled, vpn, mock)
    assert r.allowed is allowed
    assert allowed or r.reason


def test_login_flow(monkeypatch):
    monkeypatch.setattr(settings, "auth_password_hash", auth.hash_password("pw"))
    auth._fails.clear()
    c = TestClient(app)
    assert c.get("/api/tags").status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/auth/login", json={"username": "admin", "password": "bad"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "admin", "password": "pw"}).status_code == 200
    assert c.get("/api/auth/me").json() == {"user": "admin"}
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_login_throttle_and_unconfigured(monkeypatch):
    auth._fails.clear()
    c = TestClient(app)
    monkeypatch.setattr(settings, "auth_password_hash", "")
    assert c.post("/api/auth/login", json={"username": "a", "password": "b"}).status_code == 503
    monkeypatch.setattr(settings, "auth_password_hash", auth.hash_password("pw"))
    for _ in range(5):
        c.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert c.post("/api/auth/login", json={"username": "admin", "password": "pw"}).status_code == 429
    auth._fails.clear()


def test_tampered_cookie_rejected():
    c = TestClient(app)
    c.cookies.set(auth.COOKIE, "garbage")
    assert c.get("/api/auth/me").status_code == 401
    assert auth_api  # imported for coverage of module wiring
