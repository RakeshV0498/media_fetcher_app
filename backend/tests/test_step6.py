import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.download import service
from app.download.agent import AgentClient
from app.download.gate import GateResult, check_gate, enough_space, vpn_healthy
from app.download.qbittorrent import QBittorrentClient
from app.models import Download, Node, Release, Source, Tag, Variant

QB = "http://qb:8080"


# ---------------- pure gate logic ----------------
@pytest.mark.parametrize("running,vpn,home,ok", [
    (True, "5.5.5.5", "1.1.1.1", True),
    (False, "5.5.5.5", "1.1.1.1", False),   # tunnel down
    (True, None, "1.1.1.1", False),         # vpn ip unknown
    (True, "5.5.5.5", None, False),         # home ip unknown -> fail closed
    (True, "1.1.1.1", "1.1.1.1", False),    # leak: same IP as home
])
def test_vpn_healthy(running, vpn, home, ok):
    r = vpn_healthy(running, vpn, home)
    assert r.allowed is ok and (ok or "VPN" in r.reason)


def test_check_gate_requires_flag_and_vpn():
    good, bad = GateResult(True), GateResult(False, "VPN health check failed: x")
    assert not check_gate(False, good, False).allowed          # flag off
    assert check_gate(True, bad, False).reason.startswith("VPN")
    assert check_gate(True, good, False).allowed
    assert check_gate(False, bad, True).allowed                # mock bypasses


def test_enough_space():
    gb = 1024**3
    assert enough_space(20 * gb, 10 * gb, 5 * gb).allowed
    assert not enough_space(14 * gb, 10 * gb, 5 * gb).allowed   # 11 + 5 > 14
    assert not enough_space(4 * gb, None, 5 * gb).allowed


# ---------------- qBittorrent client ----------------
def _qb_mocks():
    respx.post(f"{QB}/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Ok."))
    return respx.post(f"{QB}/api/v2/app/setPreferences").mock(return_value=httpx.Response(200))


@respx.mock
def test_qbit_add_sets_no_seeding_and_returns_tag():
    prefs = _qb_mocks()
    add = respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Ok."))
    c = QBittorrentClient(QB, "u", "p", max_active=2)
    cid = c.add("magnet:?xt=urn:btih:abc", "tv", "/mnt/d/tv")
    body = add.calls[0].request.content.decode()
    assert "ratioLimit=0" in body and "seedingTimeLimit=0" in body and "savepath=%2Fmnt%2Fd%2Ftv" in body
    assert cid.startswith("mf-") and cid in body
    p = json.loads(__import__("urllib.parse").parse.parse_qs(prefs.calls[0].request.content.decode())["json"][0])
    assert p["max_ratio"] == 0 and p["max_active_downloads"] == 2


@respx.mock
def test_qbit_login_failure_and_rejected_add():
    respx.post(f"{QB}/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Fails."))
    with pytest.raises(RuntimeError, match="login failed"):
        QBittorrentClient(QB, "u", "bad").add("m", "c", "/p")
    respx.post(f"{QB}/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Ok."))
    respx.post(f"{QB}/api/v2/app/setPreferences").mock(return_value=httpx.Response(200))
    respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Fails."))
    with pytest.raises(RuntimeError, match="rejected"):
        QBittorrentClient(QB, "u", "p").add("m", "c", "/p")


@respx.mock
@pytest.mark.parametrize("state,prog,expected", [
    ("downloading", 0.4, "downloading"), ("stalledDL", 0.1, "downloading"), ("metaDL", 0, "downloading"),
    ("pausedDL", 0.4, "paused"), ("stoppedDL", 0.4, "paused"),
    ("uploading", 1.0, "done"), ("pausedUP", 1.0, "done"), ("stoppedUP", 1.0, "done"),
    ("error", 0.2, "failed"), ("missingFiles", 0.2, "failed"),
])
def test_qbit_status_mapping(state, prog, expected):
    _qb_mocks()
    respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=httpx.Response(200, json=[{
        "hash": "h", "state": state, "progress": prog, "dlspeed": 1000, "eta": 8640000,
        "content_path": "/mnt/d/x"}]))
    p = QBittorrentClient(QB, "u", "p").status("mf-1")
    assert p.state == expected and p.eta is None and p.content_path == "/mnt/d/x"


@respx.mock
def test_qbit_missing_torrent_pause_fallback_and_remove_keeps_files():
    _qb_mocks()
    info = respx.get(f"{QB}/api/v2/torrents/info").mock(return_value=httpx.Response(200, json=[]))
    c = QBittorrentClient(QB, "u", "p")
    assert c.status("gone") is None
    info.mock(return_value=httpx.Response(200, json=[{"hash": "h", "state": "downloading", "progress": 0.5}]))
    respx.post(f"{QB}/api/v2/torrents/stop").mock(return_value=httpx.Response(404))   # qBittorrent 4.x
    pause = respx.post(f"{QB}/api/v2/torrents/pause").mock(return_value=httpx.Response(200))
    c.pause("t")
    assert pause.called
    delete = respx.post(f"{QB}/api/v2/torrents/delete").mock(return_value=httpx.Response(200))
    c.remove("t", delete_files=False)
    assert "deleteFiles=false" in delete.calls[0].request.content.decode()


@respx.mock
def test_qbit_relogin_on_403():
    login = respx.post(f"{QB}/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Ok."))
    respx.post(f"{QB}/api/v2/app/setPreferences").mock(return_value=httpx.Response(200))
    respx.get(f"{QB}/api/v2/torrents/info").mock(side_effect=[httpx.Response(403), httpx.Response(200, json=[])])
    QBittorrentClient(QB, "u", "p").status("t")
    assert login.call_count == 2


# ---------------- node agent ----------------
@pytest.fixture()
def agent_app(tmp_path, monkeypatch):
    from agent import main as agent_main
    media, dls = tmp_path / "media", tmp_path / "dl"
    media.mkdir(), dls.mkdir()
    monkeypatch.setenv("NODE_AGENT_TOKEN", "tok")
    monkeypatch.setenv("MEDIA_ROOTS", str(media))
    monkeypatch.setenv("DOWNLOAD_ROOTS", str(dls))
    c = TestClient(agent_main.app, headers={"Authorization": "Bearer tok"})
    return c, media, dls


def test_agent_auth_fails_closed(agent_app, monkeypatch):
    c, _, _ = agent_app
    assert TestClient(c.app).get("/health").status_code == 401
    assert TestClient(c.app, headers={"Authorization": "Bearer nope"}).get("/health").status_code == 401
    monkeypatch.delenv("NODE_AGENT_TOKEN")
    assert TestClient(c.app, headers={"Authorization": "Bearer "}).get("/health").status_code == 503


def test_agent_disk_enforces_roots(agent_app, tmp_path):
    c, media, _ = agent_app
    assert c.get("/disk", params={"path": str(media / "tv" / "new")}).json()["free_bytes"] > 0
    assert c.get("/disk", params={"path": str(tmp_path)}).status_code == 403


def test_agent_postprocess_moves_and_enforces_both_roots(agent_app, tmp_path):
    c, media, dls = agent_app
    f = dls / "Cool.Show.S01E02.1080p.mkv"
    with open(f, "wb") as fh:
        fh.truncate(60 * 1024 * 1024)
    body = {"content_path": str(f), "root": str(media / "tv"), "kind": "tv", "title": "Cool Show"}
    r = c.post("/postprocess", json={**body, "content_path": str(tmp_path / "evil.mkv")})
    assert r.status_code == 403                                            # source outside DOWNLOAD_ROOTS
    assert c.post("/postprocess", json={**body, "root": str(tmp_path / "x")}).status_code == 403  # dest outside MEDIA_ROOTS
    r = c.post("/postprocess", json=body)
    assert r.status_code == 200
    assert (media / "tv" / "Cool Show" / "Season 01" / "Cool Show - S01E02.mkv").exists()
    assert c.post("/postprocess", json=body).status_code == 404            # already moved


def test_agent_postprocess_needs_attention_is_422(agent_app):
    c, media, dls = agent_app
    f = dls / "[G] One Piece - 1056 (1080p).mkv"
    with open(f, "wb") as fh:
        fh.truncate(60 * 1024 * 1024)
    r = c.post("/postprocess", json={"content_path": str(f), "root": str(media / "anime"),
                                     "kind": "tv", "title": "One Piece"})
    assert r.status_code == 422 and f.exists()


@respx.mock
def test_agent_vpn_reports_status_and_home_ip(agent_app):
    c, _, _ = agent_app
    respx.get("http://gluetun:8000/v1/vpn/status").mock(return_value=httpx.Response(200, json={"status": "running"}))
    respx.get("http://gluetun:8000/v1/publicip/ip").mock(return_value=httpx.Response(200, json={"public_ip": "5.5.5.5"}))
    respx.get("https://api.ipify.org").mock(return_value=httpx.Response(200, text="1.1.1.1"))
    assert c.get("/vpn").json() == {"vpn_status": "running", "vpn_ip": "5.5.5.5", "home_ip": "1.1.1.1", "error": None}


@respx.mock
def test_agent_vpn_falls_back_to_old_endpoint_and_reports_errors(agent_app):
    c, _, _ = agent_app
    respx.get("http://gluetun:8000/v1/vpn/status").mock(return_value=httpx.Response(404))
    respx.get("http://gluetun:8000/v1/openvpn/status").mock(return_value=httpx.Response(200, json={"status": "running"}))
    respx.get("http://gluetun:8000/v1/publicip/ip").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://api.ipify.org").mock(return_value=httpx.Response(200, text="1.1.1.1"))
    d = c.get("/vpn").json()
    assert d["vpn_status"] == "running" and d["vpn_ip"] is None and "publicip" in d["error"]


# ---------------- controller -> agent client & full approve/finalize path ----------------
AGENT = "http://agent:8800"


@respx.mock
def test_agent_client_vpn_fails_closed():
    a = AgentClient(AGENT, "t")
    respx.get(f"{AGENT}/vpn").mock(return_value=httpx.Response(200, json={
        "vpn_status": "running", "vpn_ip": "5.5.5.5", "home_ip": "1.1.1.1"}))
    assert a.vpn().gate.allowed
    assert a.vpn(home_ip_override="5.5.5.5").gate.allowed is False        # override honoured
    respx.get(f"{AGENT}/vpn").mock(side_effect=httpx.ConnectError("x"))
    assert not a.vpn().gate.allowed                                        # unreachable agent
    respx.get(f"{AGENT}/vpn").mock(return_value=httpx.Response(401))
    assert not a.vpn().gate.allowed


class FakeQbit:
    is_mock = False

    def __init__(self):
        self.added, self.removed = [], []

    def add(self, uri, category, save_path):
        self.added.append((uri, category, save_path))
        return "mf-1"

    def status(self, cid):
        return None

    def remove(self, cid, delete_files=False):
        self.removed.append((cid, delete_files))


@pytest.fixture()
def real_setup(db, monkeypatch):
    monkeypatch.setattr(service, "_client", None)
    monkeypatch.setattr(settings, "download_client", "qbittorrent")
    monkeypatch.setattr(settings, "downloads_enabled", True)
    monkeypatch.setattr(settings, "require_vpn", True)   # these tests exercise the VPN gate
    monkeypatch.setattr(settings, "home_public_ip", "")
    node = db.scalar(select(Node).where(Node.name == "pi4"))
    node.agent_url, node.qbit_url, node.download_dir = AGENT, QB, "/mnt/dl"
    tag = db.scalar(select(Tag).where(Tag.name == "TV Show"))
    tag.final_path = "/mnt/disk2/tv"
    src = Source(name="s", url="u")
    db.add(src)
    db.flush()
    rel = Release(release_key="k", title="Cool Show", kind="tv", season=1, episode=2)
    db.add(rel)
    db.flush()
    var = Variant(release_id=rel.id, source_id=src.id, ident="i", quality="1080p",
                  size_bytes=2 * 1024**3, magnet="magnet:?xt=urn:btih:1")
    db.add(var)
    db.commit()
    fake = FakeQbit()
    monkeypatch.setitem(service._qbit, f"pi4|{QB}", fake)
    return rel, var, tag, fake


def _agent_ok(free=500 * 1024**3, vpn_ip="5.5.5.5"):
    respx.get(f"{AGENT}/vpn").mock(return_value=httpx.Response(200, json={
        "vpn_status": "running", "vpn_ip": vpn_ip, "home_ip": "1.1.1.1"}))
    respx.get(f"{AGENT}/disk").mock(return_value=httpx.Response(200, json={"free_bytes": free}))


@respx.mock
def test_approve_real_client_happy_path(db, real_setup):
    rel, var, tag, fake = real_setup
    _agent_ok()
    dl = service.approve(db, rel.id, var.id, tag.id)
    # qBittorrent must save into the node's DOWNLOAD folder (which it can see), never the library folder
    assert fake.added == [("magnet:?xt=urn:btih:1", "tv", "/mnt/dl/tv")] and dl.node_name == "pi4"


@respx.mock
def test_approve_blocked_when_vpn_leaks_or_disk_full_or_flag_off(db, real_setup, monkeypatch):
    rel, var, tag, fake = real_setup
    _agent_ok(vpn_ip="1.1.1.1")                                           # VPN IP == home IP
    with pytest.raises(service.ApproveError, match="equals home IP"):
        service.approve(db, rel.id, var.id, tag.id)
    _agent_ok(free=1024**3)                                               # 1 GB free
    with pytest.raises(service.ApproveError, match="disk space"):
        service.approve(db, rel.id, var.id, tag.id)
    _agent_ok()
    monkeypatch.setattr(settings, "downloads_enabled", False)
    with pytest.raises(service.ApproveError, match="disabled"):
        service.approve(db, rel.id, var.id, tag.id)
    assert fake.added == [] and rel.status == "new"                       # nothing ever reached qBittorrent


def test_approve_blocked_when_node_has_no_agent(db, real_setup):
    rel, var, tag, fake = real_setup
    tag.node.agent_url = ""
    with pytest.raises(service.ApproveError, match="no node agent"):
        service.approve(db, rel.id, var.id, tag.id)
    assert fake.added == []


@respx.mock
def test_finalize_delegates_move_to_node_agent(db, real_setup, monkeypatch):
    rel, var, tag, fake = real_setup
    monkeypatch.setattr(service, "refresh_library", lambda *a, **k: True)
    d = Download(release_id=rel.id, variant_id=var.id, tag_id=tag.id, client_id="mf-1",
                 status="downloading", content_path="/mnt/dl/Cool.Show.S01E02.mkv")
    db.add(d)
    db.commit()
    route = respx.post(f"{AGENT}/postprocess").mock(return_value=httpx.Response(200, json={
        "moved": [["/mnt/dl/a.mkv", "/mnt/disk2/tv/Cool Show/Season 01/Cool Show - S01E02.mkv"]],
        "duplicates": [], "skipped": []}))
    service.finalize(db, d, fake)
    sent = json.loads(route.calls[0].request.content)
    assert sent["root"] == "/mnt/disk2/tv" and sent["title"] == "Cool Show"
    assert d.status == "done" and fake.removed == [("mf-1", False)]       # stopped, files kept, not seeded
    respx.post(f"{AGENT}/postprocess").mock(return_value=httpx.Response(422, json={"detail": "need season"}))
    d.status, d.client_id = "downloading", ""
    service.finalize(db, d, fake)
    assert d.status == "needs_attention" and d.error == "need season"
    respx.post(f"{AGENT}/postprocess").mock(side_effect=httpx.ConnectError("down"))
    service.finalize(db, d, fake)
    assert d.status == "failed" and "unreachable" in d.error


@respx.mock
def test_download_dir_defaults_to_agent_root_and_both_disks_are_checked(db, real_setup):
    rel, var, tag, fake = real_setup
    tag.node.download_dir = ""                                              # blank -> ask the agent
    respx.get(f"{AGENT}/info").mock(return_value=httpx.Response(200, json={"download_roots": ["/mnt/agent-dl"], "media_roots": []}))
    respx.get(f"{AGENT}/vpn").mock(return_value=httpx.Response(200, json={
        "vpn_status": "running", "vpn_ip": "5.5.5.5", "home_ip": "1.1.1.1"}))
    disk = respx.get(f"{AGENT}/disk").mock(return_value=httpx.Response(200, json={"free_bytes": 500 * 1024**3}))
    service.approve(db, rel.id, var.id, tag.id)
    assert fake.added[0][2] == "/mnt/agent-dl/tv"
    checked = {c.request.url.params["path"] for c in disk.calls}
    assert checked == {"/mnt/agent-dl", "/mnt/disk2/tv"}                    # where it lands AND where it ends up


@respx.mock
def test_no_download_dir_anywhere_blocks_approval(db, real_setup):
    rel, var, tag, fake = real_setup
    tag.node.download_dir = ""
    respx.get(f"{AGENT}/info").mock(return_value=httpx.Response(200, json={"download_roots": [], "media_roots": []}))
    respx.get(f"{AGENT}/vpn").mock(return_value=httpx.Response(200, json={
        "vpn_status": "running", "vpn_ip": "5.5.5.5", "home_ip": "1.1.1.1"}))
    with pytest.raises(service.ApproveError, match="no download folder"):
        service.approve(db, rel.id, var.id, tag.id)
    assert fake.added == []


@respx.mock
def test_download_disk_full_blocks_even_if_library_disk_has_room(db, real_setup):
    rel, var, tag, fake = real_setup
    respx.get(f"{AGENT}/vpn").mock(return_value=httpx.Response(200, json={
        "vpn_status": "running", "vpn_ip": "5.5.5.5", "home_ip": "1.1.1.1"}))
    respx.get(f"{AGENT}/disk", params={"path": "/mnt/dl"}).mock(return_value=httpx.Response(200, json={"free_bytes": 1024**3}))
    respx.get(f"{AGENT}/disk", params={"path": "/mnt/disk2/tv"}).mock(return_value=httpx.Response(200, json={"free_bytes": 900 * 1024**3}))
    with pytest.raises(service.ApproveError, match=r"disk space.*/mnt/dl"):
        service.approve(db, rel.id, var.id, tag.id)
    assert fake.added == []


# ---------------- VPN is optional ----------------
@respx.mock
def test_downloads_work_without_vpn_by_default(db, real_setup, monkeypatch):
    rel, var, tag, fake = real_setup
    monkeypatch.setattr(settings, "require_vpn", False)
    vpn = respx.get(f"{AGENT}/vpn").mock(side_effect=httpx.ConnectError("no gluetun on this node"))
    respx.get(f"{AGENT}/disk").mock(return_value=httpx.Response(200, json={"free_bytes": 500 * 1024**3}))
    service.approve(db, rel.id, var.id, tag.id)
    assert fake.added == [("magnet:?xt=urn:btih:1", "tv", "/mnt/dl/tv")]
    assert not vpn.called                                                   # VPN is not even consulted


@respx.mock
def test_without_vpn_the_master_switch_disk_and_agent_checks_still_apply(db, real_setup, monkeypatch):
    rel, var, tag, fake = real_setup
    monkeypatch.setattr(settings, "require_vpn", False)
    monkeypatch.setattr(settings, "downloads_enabled", False)
    with pytest.raises(service.ApproveError, match="disabled"):
        service.approve(db, rel.id, var.id, tag.id)
    monkeypatch.setattr(settings, "downloads_enabled", True)
    respx.get(f"{AGENT}/disk").mock(return_value=httpx.Response(200, json={"free_bytes": 1024**3}))
    with pytest.raises(service.ApproveError, match="disk space"):
        service.approve(db, rel.id, var.id, tag.id)
    tag.node.agent_url = ""
    with pytest.raises(service.ApproveError, match="no node agent"):
        service.approve(db, rel.id, var.id, tag.id)
    assert fake.added == []


def test_default_library_paths_are_the_real_folders(db):
    from app.models import Tag
    paths = {t.name: t.final_path for t in db.scalars(select(Tag))}
    assert paths == {"Tamil Movie": "/Media_Server/05/Tamil Movies", "English Movie": "/Media_Server/05/English Movies",
                     "Dubbed Movie": "/Media_Server/05/Dubbed Movies",
                     "Indian Language Movie": "/Media_Server/05/Indian Language Movies",
                     "TV Show": "/cloud/01", "Anime": "/cloud/02/Anime"}


def test_require_vpn_defaults_off_and_is_an_editable_setting(api_client):
    assert settings.require_vpn is False
    fields = {f["key"]: f for f in api_client.get("/api/app-settings").json()["fields"]}
    assert fields["require_vpn"]["group"] == "downloads" and fields["require_vpn"]["value"] is False
    api_client.put("/api/app-settings", json={"values": {"require_vpn": True}})
    assert settings.require_vpn is True
