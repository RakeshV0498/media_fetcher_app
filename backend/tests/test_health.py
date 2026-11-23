from fastapi.testclient import TestClient

from app.main import app


def test_health_downloads_disabled_by_default() -> None:
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["downloads_enabled"] is False
