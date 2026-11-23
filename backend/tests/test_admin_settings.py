import httpx
import pytest
import respx
from sqlalchemy import select

from app import auth, settings_store as store
from app.config import settings
from app.download import service
from app.models import AppSetting, Node

AGENT = "http://agent:8800"


@pytest.fixture(autouse=True)
def _restore_settings():
    saved = settings.model_copy()
    yield
    for k, v in saved.model_dump().items():
        setattr(settings, k, v)


# ---------------- store ----------------
def test_secret_encrypted_at_rest_and_roundtrips(db):
    store.save(db, store.Update(values={"tmdb_api_key": "super-secret-key", "jellyfin_url": "http://jf:8096"}))
    row = db.get(AppSetting, "tmdb_api_key")
    assert row.is_secret and "super-secret-key" not in row.value
    assert store.get(db, "tmdb_api_key") == "super-secret-key"
    assert settings.tmdb_api_key == "super-secret-key" and settings.jellyfin_url == "http://jf:8096"
    assert db.get(AppSetting, "jellyfin_url").value == "http://jf:8096"          # non-secret stays readable


def test_describe_never_returns_secret_values(db):
    store.save(db, store.Update(values={"tmdb_api_key": "super-secret-key"}))
    fields = {f["key"]: f for f in store.describe(db)}
    assert fields["tmdb_api_key"]["set"] is True and "value" not in fields["tmdb_api_key"]
    assert "super-secret-key" not in str(fields)


def test_empty_secret_keeps_saved_value_and_clear_restores_env_default(db, monkeypatch):
    store.save(db, store.Update(values={"tmdb_api_key": "abc"}))
    store.save(db, store.Update(values={"tmdb_api_key": ""}))                    # blank = unchanged
    assert settings.tmdb_api_key == "abc"
    store.save(db, store.Update(values={"user_agent": "Custom/1"}))
    assert settings.user_agent == "Custom/1"
    store.save(db, store.Update(clear=["user_agent", "tmdb_api_key"]))
    assert settings.user_agent == store.ENV_DEFAULTS["user_agent"] and settings.tmdb_api_key == ""
    assert db.get(AppSetting, "tmdb_api_key") is None


@pytest.mark.parametrize("values,msg", [
    ({"scan_min_delay": "abc"}, "invalid float"),
    ({"scan_min_delay": -1}, "between"),
    ({"download_client": "ftp"}, "one of"),
    ({"jellyfin_url": "jellyfin.lan"}, "http"),
    ({"nope": 1}, "unknown setting"),
    ({"downloads_enabled": "maybe"}, "invalid bool"),
])
def test_validation_rejects_bad_values_without_partial_save(db, values, msg):
    with pytest.raises(store.SettingError, match=msg):
        store.save(db, store.Update(values={"user_agent": "ShouldNotSave", **values}))
    assert db.get(AppSetting, "user_agent") is None


def test_unreadable_secret_after_app_secret_change_is_treated_as_unset(db, monkeypatch):
    store.save(db, store.Update(values={"tmdb_api_key": "abc"}))
    monkeypatch.setattr(settings, "app_secret", "a-different-secret")
    store.apply_overrides(db)
    assert settings.tmdb_api_key == ""
    f = {x["key"]: x for x in store.describe(db)}["tmdb_api_key"]
    assert f["unreadable"] is True and f["set"] is False


def test_bool_and_int_coercion_applied(db):
    store.save(db, store.Update(values={"downloads_enabled": True, "min_free_reserve_gb": "12"}))
    assert settings.downloads_enabled is True and settings.min_free_reserve_gb == 12


# ---------------- API ----------------
def test_api_get_put_and_side_effects(api_client, monkeypatch):
    r = api_client.get("/api/app-settings").json()["fields"]
    assert {f["group"] for f in r} >= {"general", "integrations", "telegram", "downloads", "security"}
    service._qbit["x"] = object()
    service._client = object()
    r = api_client.put("/api/app-settings", json={"values": {"download_client": "qbittorrent", "qbit_password": "pw"}})
    assert r.status_code == 200 and "download_client" in r.json()["changed"]
    assert service._qbit == {} and service._client is None                    # caches reset
    assert "pw" not in r.text
    bad = api_client.put("/api/app-settings", json={"values": {"download_client": "x"}})
    assert bad.status_code == 422
    service._client = None


def test_telegram_restart_on_change(api_client, monkeypatch):
    from app.notify import telegram
    gen = telegram._gen
    monkeypatch.setattr(telegram.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: None})())
    api_client.put("/api/app-settings", json={"values": {"telegram_chat_id": "42"}})
    assert telegram._gen == gen + 1                                           # old poller superseded


@respx.mock
def test_connection_tests(api_client):
    settings.tmdb_api_key = "k"
    respx.get("https://api.themoviedb.org/3/configuration").mock(return_value=httpx.Response(200, json={}))
    assert api_client.post("/api/app-settings/test/tmdb").json()["ok"] is True
    respx.get("https://api.themoviedb.org/3/configuration").mock(return_value=httpx.Response(401))
    r = api_client.post("/api/app-settings/test/tmdb").json()
    assert r["ok"] is False and "401" in r["message"]
    settings.jellyfin_url, settings.jellyfin_api_key = "http://jf:8096", "k"
    respx.get("http://jf:8096/System/Info").mock(return_value=httpx.Response(200, json={"Version": "10.9"}))
    assert "10.9" in api_client.post("/api/app-settings/test/jellyfin").json()["message"]
    settings.telegram_bot_token, settings.telegram_chat_id = "T", "42"
    respx.get("https://api.telegram.org/botT/getMe").mock(return_value=httpx.Response(200, json={"result": {"username": "mybot"}}))
    send = respx.post("https://api.telegram.org/botT/sendMessage").mock(return_value=httpx.Response(200, json={}))
    assert api_client.post("/api/app-settings/test/telegram").json()["ok"] is True and send.called
    assert api_client.post("/api/app-settings/test/nope").status_code == 404


def test_change_password(api_client, db):
    settings.auth_password_hash = auth.hash_password("old-password-1")
    assert api_client.post("/api/app-settings/password", json={"current": "bad", "new": "x" * 12}).status_code == 403
    assert api_client.post("/api/app-settings/password", json={"current": "old-password-1", "new": "short"}).status_code == 422
    assert api_client.post("/api/app-settings/password", json={"current": "old-password-1", "new": "brand-new-pass"}).status_code == 200
    assert auth.verify_password("brand-new-pass", settings.auth_password_hash)
    row = db.get(AppSetting, "auth_password_hash")
    assert row is not None and row.is_secret


def test_settings_routes_require_login():
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    assert c.get("/api/app-settings").status_code == 401
    assert c.put("/api/app-settings", json={"values": {}}).status_code == 401
    assert c.post("/api/nodes/1/test").status_code == 401
    assert c.get("/api/nodes/1/browse").status_code == 401


# ---------------- folder browser ----------------
def test_browse_local_confined_to_roots(api_client, db, tmp_path):
    root = tmp_path / "media"
    (root / "tv" / "Shows").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (tmp_path / "secret").mkdir()
    (root / "escape").symlink_to(tmp_path / "secret")
    settings.media_roots = str(root)
    nid = db.scalar(select(Node.id).where(Node.name == "pi4"))
    top = api_client.get(f"/api/nodes/{nid}/browse").json()
    assert top["dirs"] == [str(root)] and top["parent"] is None
    sub = api_client.get(f"/api/nodes/{nid}/browse", params={"path": str(root)}).json()
    assert sub["dirs"] == ["tv"] and sub["parent"] == ""                      # symlink + hidden dirs hidden
    assert api_client.get(f"/api/nodes/{nid}/browse", params={"path": str(root / "tv")}).json()["parent"] == str(root)
    for bad in (str(tmp_path), str(root / "tv" / ".." / ".."), str(root / "escape"), "relative/path"):
        assert api_client.get(f"/api/nodes/{nid}/browse", params={"path": bad}).status_code == 400, bad
    made = api_client.post(f"/api/nodes/{nid}/mkdir", json={"path": str(root / "tv" / "New Show")})
    assert made.status_code == 200 and (root / "tv" / "New Show").is_dir()
    assert api_client.post(f"/api/nodes/{nid}/mkdir", json={"path": str(tmp_path / "evil")}).status_code == 400
    assert not (tmp_path / "evil").exists()


def test_browse_without_roots_is_refused(api_client, db):
    settings.media_roots = ""
    nid = db.scalar(select(Node.id).where(Node.name == "pi4"))
    assert api_client.get(f"/api/nodes/{nid}/browse").status_code == 400


@respx.mock
def test_browse_proxied_to_node_agent(api_client, db):
    n = db.scalar(select(Node).where(Node.name == "pi4"))
    n.agent_url = AGENT
    db.commit()
    respx.get(f"{AGENT}/browse").mock(return_value=httpx.Response(200, json={"path": "/mnt/d", "dirs": ["tv"], "parent": ""}))
    assert api_client.get(f"/api/nodes/{n.id}/browse", params={"path": "/mnt/d"}).json()["dirs"] == ["tv"]
    respx.get(f"{AGENT}/browse").mock(return_value=httpx.Response(403, json={"detail": "outside MEDIA_ROOTS"}))
    r = api_client.get(f"/api/nodes/{n.id}/browse", params={"path": "/etc"})
    assert r.status_code == 400 and "outside" in r.json()["detail"]


# ---------------- VPN settings ----------------
@respx.mock
def test_vpn_save_masks_secrets_and_apply_pushes_to_agent(api_client, db):
    n = db.scalar(select(Node).where(Node.name == "pi5"))
    n.agent_url = AGENT
    db.commit()
    put = respx.put(f"{AGENT}/vpn/settings").mock(return_value=httpx.Response(200, json={"applied": True}))
    r = api_client.put(f"/api/nodes/{n.id}/vpn", json={
        "provider": "protonvpn", "type": "wireguard", "countries": "Netherlands, Germany",
        "port_forwarding": True, "wireguard_private_key": "WGSECRET", "apply": True}).json()
    assert r["applied"] is True and r["settings"]["wireguard_private_key_set"] is True
    assert "WGSECRET" not in str(r)
    sent = put.calls[0].request.content.decode()
    assert '"provider":"protonvpn"' in sent.replace(" ", "") and "WGSECRET" in sent
    assert '"countries":["Netherlands","Germany"]' in sent.replace(" ", "")
    raw = db.get(AppSetting, "vpn.pi5.wireguard_private_key")
    assert raw.is_secret and "WGSECRET" not in raw.value
    got = api_client.get(f"/api/nodes/{n.id}/vpn").json()
    assert got["provider"] == "protonvpn" and got["port_forwarding"] is True and "WGSECRET" not in str(got)
    # blank secret on a later save keeps the stored one
    api_client.put(f"/api/nodes/{n.id}/vpn", json={"provider": "protonvpn", "wireguard_private_key": ""})
    assert store_get(db, "vpn.pi5.wireguard_private_key") == "WGSECRET"


def store_get(db, key):
    return store.get(db, key)


@respx.mock
def test_vpn_apply_failure_is_reported_but_saved(api_client, db):
    n = db.scalar(select(Node).where(Node.name == "pi5"))
    n.agent_url = AGENT
    db.commit()
    respx.put(f"{AGENT}/vpn/settings").mock(return_value=httpx.Response(502, json={"detail": "gluetun rejected the settings (400)"}))
    r = api_client.put(f"/api/nodes/{n.id}/vpn", json={"provider": "x", "apply": True}).json()
    assert r["saved"] is True and r["applied"] is False and "rejected" in r["message"]
    n.agent_url = ""
    db.commit()
    assert api_client.put(f"/api/nodes/{n.id}/vpn", json={"provider": "x", "apply": True}).status_code == 409
    assert api_client.put(f"/api/nodes/{n.id}/vpn", json={"type": "pptp"}).status_code == 422


@respx.mock
def test_node_test_reports_each_check(api_client, db):
    n = db.scalar(select(Node).where(Node.name == "pi5"))
    n.agent_url, n.qbit_url = AGENT, "http://qb:8080"
    db.commit()
    respx.get(f"{AGENT}/vpn").mock(return_value=httpx.Response(200, json={"vpn_status": "running", "vpn_ip": "5.5.5.5", "home_ip": "1.1.1.1"}))
    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Fails."))
    checks = {c["name"]: c for c in api_client.post(f"/api/nodes/{n.id}/test").json()["checks"]}
    assert checks["Node agent + VPN"]["ok"] is True and checks["qBittorrent"]["ok"] is False
