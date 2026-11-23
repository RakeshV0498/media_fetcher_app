import httpx
import respx
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.scanner import scheduler
from tests.test_scanner import HTML, SEL


@respx.mock
def test_sources_scan_and_releases(session_factory, monkeypatch):
    def override():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr("app.scanner.runner.settings.scan_min_delay", 0)
    monkeypatch.setattr("app.scanner.runner.settings.scan_max_delay", 0)
    respx.get("http://site/list").mock(return_value=httpx.Response(200, text=HTML))
    try:
        c = TestClient(app)
        r = c.post("/api/sources", json={"name": "s", "url": "http://site/list",
                                         "mode": "html", "selectors": SEL})
        assert r.status_code == 201
        sid = r.json()["id"]
        assert c.post(f"/api/sources/{sid}/scan").json()["status"].startswith("ok")
        rel = c.get("/api/releases").json()
        assert len(rel) == 1 and [v["seeders"] for v in rel[0]["variants"]] == [88, 12]
        assert len(c.get("/api/tags").json()) == 6
        assert c.delete(f"/api/sources/{sid}").status_code == 204
    finally:
        app.dependency_overrides.clear()
