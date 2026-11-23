import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import require_user
from app.config import settings
from app.db import get_db
from app.download import service
from app.download.mock import MockClient
from app.main import app
from app.models import Download, Release, Source, Tag, Variant


@pytest.fixture()
def client(session_factory, monkeypatch):
    def override():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[require_user] = lambda: "admin"
    monkeypatch.setattr(service, "_client", MockClient())
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def data(session_factory):
    with session_factory() as db:
        src = Source(name="s", url="http://x")
        db.add(src)
        db.flush()
        r1 = Release(release_key="a", title="Cool Show", kind="tv", season=1, episode=2,
                     suggested_tag_id=db.scalar(select(Tag.id).where(Tag.name == "TV Show")))
        r2 = Release(release_key="b", title="Other Movie", kind="movie", year=2020)
        db.add_all([r1, r2])
        db.flush()
        vs = [Variant(release_id=r1.id, source_id=src.id, ident=f"i{i}", quality=q,
                      seeders=s, magnet=f"magnet:?xt=urn:btih:{i}")
              for i, (q, s) in enumerate([("720p", 100), ("1080p", 10), ("1080p", 50)])]
        other = Variant(release_id=r2.id, source_id=src.id, ident="z", quality="720p",
                        magnet="magnet:?xt=urn:btih:z")
        db.add_all(vs + [other])
        db.commit()
        return {"r1": r1.id, "r2": r2.id, "vs": [v.id for v in vs], "other": other.id,
                "tv": db.scalar(select(Tag.id).where(Tag.name == "TV Show")), "src": src.id}


def test_approve_creates_download(client, data, session_factory):
    r = client.post(f"/api/releases/{data['r1']}/approve",
                    json={"variant_id": data["vs"][0], "tag_id": data["tv"]})
    assert r.status_code == 200
    with session_factory() as db:
        assert db.get(Release, data["r1"]).status == "approved"
        d = db.scalars(select(Download)).one()
        assert d.node_name == "pi4" and d.variant_id == data["vs"][0]
    rows = client.get("/api/downloads").json()
    assert rows[0]["status"] == "downloading" and rows[0]["tag"] == "TV Show"
    assert client.post(f"/api/downloads/{rows[0]['id']}/pause").json()["status"] == "paused"
    assert client.post(f"/api/downloads/{rows[0]['id']}/resume").status_code == 200
    assert client.delete(f"/api/downloads/{rows[0]['id']}").status_code == 204


def test_variant_must_belong_to_release(client, data):
    r = client.post(f"/api/releases/{data['r1']}/approve",
                    json={"variant_id": data["other"], "tag_id": data["tv"]})
    assert r.status_code == 400


def test_blocked_gate_leaves_release_new(client, data, session_factory, monkeypatch):
    class Real(MockClient):
        is_mock = False
    monkeypatch.setattr(service, "_client", Real())
    monkeypatch.setattr(settings, "downloads_enabled", False)
    monkeypatch.setattr(settings, "require_vpn", True)
    r = client.post(f"/api/releases/{data['r1']}/approve",
                    json={"variant_id": data["vs"][0], "tag_id": data["tv"]})
    assert r.status_code == 409 and "disabled" in r.json()["detail"]
    with session_factory() as db:
        assert db.get(Release, data["r1"]).status == "new"
        assert db.scalars(select(Download)).first() is None
    monkeypatch.setattr(settings, "downloads_enabled", True)  # flag alone is not enough
    r = client.post(f"/api/releases/{data['r1']}/approve",
                    json={"variant_id": data["vs"][0], "tag_id": data["tv"]})
    assert r.status_code == 409 and "VPN" in r.json()["detail"]


def test_reject_snooze_and_filters(client, data):
    assert client.post(f"/api/releases/{data['r2']}/reject").status_code == 200
    assert [r["id"] for r in client.get("/api/releases?status=rejected").json()] == [data["r2"]]
    assert client.post(f"/api/releases/{data['r1']}/snooze", json={"hours": 1}).status_code == 200
    assert client.get("/api/releases").json() == []
    assert len(client.get("/api/releases?status=snoozed&kind=tv").json()) == 1
    assert client.get(f"/api/releases?status=snoozed&source_id={data['src']}").json()
    assert client.get("/api/releases?status=snoozed&q=nomatch").json() == []
    assert client.get(f"/api/releases?status=snoozed&tag_id={data['tv']}").json()


def test_bulk_picks_top_seeded_preferred_quality(client, data, session_factory):
    r = client.post("/api/releases/bulk",
                    json={"ids": [data["r1"], data["r2"]], "action": "approve"}).json()
    assert r["done"] == [data["r1"]]
    assert data["r2"] in {int(k) for k in r["skipped"]}  # no tag/variant at 1080p
    with session_factory() as db:
        assert db.scalars(select(Download)).one().variant_id == data["vs"][2]  # 1080p, 50 seeders
