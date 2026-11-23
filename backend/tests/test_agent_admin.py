import httpx
import pytest
import respx
from fastapi.testclient import TestClient

GL = "http://gluetun:8000"


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    from agent import main as m
    media = tmp_path / "media"
    (media / "tv").mkdir(parents=True)
    monkeypatch.setenv("NODE_AGENT_TOKEN", "tok")
    monkeypatch.setenv("MEDIA_ROOTS", str(media))
    monkeypatch.setenv("DOWNLOAD_ROOTS", str(tmp_path / "dl"))
    monkeypatch.setenv("GLUETUN_API_KEY", "gk")
    return TestClient(m.app, headers={"Authorization": "Bearer tok"}), media, m


def test_agent_browse_and_mkdir_confined(agent, tmp_path):
    c, media, _ = agent
    assert c.get("/browse").json()["dirs"] == [str(media)]
    assert c.get("/browse", params={"path": str(media)}).json()["dirs"] == ["tv"]
    assert c.get("/browse", params={"path": str(tmp_path)}).status_code == 403
    assert c.get("/browse", params={"path": str(media / "nope")}).status_code == 404
    assert c.post("/mkdir", json={"path": str(media / "tv" / "New")}).status_code == 200
    assert (media / "tv" / "New").is_dir()
    assert c.post("/mkdir", json={"path": str(media / ".." / "evil")}).status_code == 403
    assert not (tmp_path / "evil").exists()


def test_merge_vpn_preserves_unknown_fields_and_sets_ours(agent):
    _, _, m = agent
    cur = {"vpn": {"type": "openvpn", "provider": {"name": "old", "extra": 1, "server_selection": {"vpn": "openvpn"}},
                   "wireguard": {"mtu": 1400}}, "other": {"keep": True}}
    out = m.merge_vpn(cur, m.VpnSettings(provider="protonvpn", type="wireguard", countries=["NL"], port_forwarding=True,
                                         wireguard_private_key="K", wireguard_addresses=["10.2.0.2/32"]))
    v = out["vpn"]
    assert v["type"] == "wireguard" and v["provider"]["name"] == "protonvpn" and v["provider"]["extra"] == 1
    assert v["provider"]["server_selection"] == {"vpn": "openvpn", "countries": ["NL"]}
    assert v["provider"]["port_forwarding"]["enabled"] is True
    assert v["wireguard"] == {"mtu": 1400, "private_key": "K", "addresses": ["10.2.0.2/32"]} and out["other"] == {"keep": True}
    assert cur["vpn"]["provider"]["name"] == "old"                            # input not mutated
    blank = m.merge_vpn(out, m.VpnSettings())
    assert blank == out                                                       # empty update changes nothing


@respx.mock
def test_agent_vpn_settings_get_put(agent):
    c, _, _ = agent
    doc = {"vpn": {"type": "wireguard", "provider": {"name": "protonvpn", "server_selection": {"countries": ["NL"]}},
                   "wireguard": {"private_key": "SECRET"}}}
    respx.get(f"{GL}/v1/vpn/settings").mock(return_value=httpx.Response(200, json=doc))
    put = respx.put(f"{GL}/v1/vpn/settings").mock(return_value=httpx.Response(200, json={}))
    view = c.get("/vpn/settings").json()
    assert view["provider"] == "protonvpn" and view["wireguard_private_key_set"] is True and "SECRET" not in str(view)
    assert respx.calls[0].request.headers["X-API-Key"] == "gk"
    assert c.put("/vpn/settings", json={"countries": ["DE"]}).json() == {"applied": True}
    assert b'"DE"' in put.calls[0].request.content and b"SECRET" in put.calls[0].request.content
    respx.put(f"{GL}/v1/vpn/settings").mock(return_value=httpx.Response(400, text="bad provider"))
    r = c.put("/vpn/settings", json={"provider": "zzz"})
    assert r.status_code == 502 and "rejected" in r.json()["detail"]


def test_agent_vpn_settings_need_gluetun_api_key(agent, monkeypatch):
    c, _, _ = agent
    monkeypatch.delenv("GLUETUN_API_KEY")
    r = c.get("/vpn/settings")
    assert r.status_code == 503 and "GLUETUN_API_KEY" in r.json()["detail"]
