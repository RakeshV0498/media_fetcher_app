"""Thin per-Pi agent. Runs beside gluetun + qBittorrent (NOT inside gluetun's network namespace),
so its own public IP is the home IP and gluetun's control API reports the VPN IP."""
from __future__ import annotations

import hmac
import os
import shutil
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.postprocess.browse import browse, make_dir
from app.postprocess.mover import NeedsAttention, PathNotAllowed, cleanup_empty, file_release

GLUETUN_URL = os.environ.get("GLUETUN_URL", "http://gluetun:8000")
IP_CHECK_URL = os.environ.get("IP_CHECK_URL", "https://api.ipify.org")


def _roots(var: str) -> list[Path]:
    return [Path(p.strip()) for p in os.environ.get(var, "").split(",") if p.strip()]


def auth(authorization: str = Header(default="")) -> None:
    token = os.environ.get("NODE_AGENT_TOKEN", "")
    if not token:
        raise HTTPException(503, "NODE_AGENT_TOKEN is not configured")
    if not hmac.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(401, "bad token")


app = FastAPI(title="Media Fetcher node agent", dependencies=[Depends(auth)])


def _inside(path: Path, roots: list[Path]) -> bool:
    p = path.resolve()
    return any(p == r.resolve() or r.resolve() in p.parents for r in roots)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


def _get_json(http: httpx.Client, path: str) -> dict:
    r = http.get(f"{GLUETUN_URL}{path}")
    r.raise_for_status()
    return r.json()


@app.get("/vpn")
def vpn() -> dict[str, str | None]:
    out: dict[str, str | None] = {"vpn_status": None, "vpn_ip": None, "home_ip": None, "error": None}
    with httpx.Client(timeout=8) as http:
        for path in ("/v1/vpn/status", "/v1/openvpn/status"):  # newer, then older gluetun
            try:
                out["vpn_status"] = _get_json(http, path).get("status")
                break
            except (httpx.HTTPError, ValueError) as e:
                out["error"] = f"gluetun status: {e}"
        try:
            out["vpn_ip"] = _get_json(http, "/v1/publicip/ip").get("public_ip") or None
        except (httpx.HTTPError, ValueError) as e:
            out["error"] = f"gluetun publicip: {e}"
        try:  # direct (not via VPN) -> the home IP
            out["home_ip"] = http.get(IP_CHECK_URL).text.strip() or None
        except httpx.HTTPError as e:
            out["error"] = f"home ip check: {e}"
    return out


@app.get("/disk")
def disk(path: str) -> dict[str, int]:
    roots = _roots("MEDIA_ROOTS")
    p = Path(path)
    if not roots or not _inside(p, roots):
        raise HTTPException(403, f"{path} is outside MEDIA_ROOTS")
    while not p.exists() and p != p.parent:
        p = p.parent
    return {"free_bytes": shutil.disk_usage(p).free}


class PostProcess(BaseModel):
    content_path: str
    root: str
    kind: str
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None


@app.post("/postprocess")
def postprocess(b: PostProcess) -> dict[str, list]:
    media, downloads = _roots("MEDIA_ROOTS"), _roots("DOWNLOAD_ROOTS")
    if not media or not downloads:
        raise HTTPException(503, "MEDIA_ROOTS and DOWNLOAD_ROOTS must be configured")
    if not _inside(Path(b.content_path), downloads):
        raise HTTPException(403, f"{b.content_path} is outside DOWNLOAD_ROOTS")
    try:
        res = file_release(Path(b.content_path), Path(b.root), b.kind, b.title, b.year,
                           b.season, b.episode, allowed_roots=media)
    except NeedsAttention as e:
        raise HTTPException(422, str(e)) from e
    except PathNotAllowed as e:
        raise HTTPException(403, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    if not res.duplicates:
        cleanup_empty(Path(b.content_path))
    return {"moved": [[str(a), str(d)] for a, d in res.moved],
            "duplicates": [str(p) for p in res.duplicates], "skipped": [str(p) for p in res.skipped]}


# ---------------- folder browsing (never outside MEDIA_ROOTS) ----------------
@app.get("/browse")
def browse_dirs(path: str = "") -> dict:
    try:
        return browse(path, _roots("MEDIA_ROOTS"))
    except PathNotAllowed as e:
        raise HTTPException(403, str(e)) from e
    except NotADirectoryError as e:
        raise HTTPException(404, str(e)) from e


class MkDir(BaseModel):
    path: str


@app.post("/mkdir")
def mkdir(b: MkDir) -> dict[str, str]:
    try:
        return make_dir(b.path, _roots("MEDIA_ROOTS"))
    except PathNotAllowed as e:
        raise HTTPException(403, str(e)) from e


# ---------------- VPN provider settings -> gluetun control API ----------------
GLUETUN_API_KEY_ENV = "GLUETUN_API_KEY"


class VpnSettings(BaseModel):
    provider: str | None = None
    type: str | None = None  # wireguard | openvpn
    countries: list[str] | None = None
    port_forwarding: bool | None = None
    wireguard_private_key: str | None = None
    wireguard_addresses: list[str] | None = None
    openvpn_user: str | None = None
    openvpn_password: str | None = None


def merge_vpn(current: dict, v: VpnSettings) -> dict:
    """Merge our fields into gluetun's own settings document (so unknown fields are preserved)."""
    import copy
    doc = copy.deepcopy(current) if current else {}
    vpn = doc.setdefault("vpn", {})
    prov = vpn.setdefault("provider", {})
    sel = prov.setdefault("server_selection", {})
    if v.type:
        vpn["type"] = v.type
    if v.provider:
        prov["name"] = v.provider
    if v.countries is not None:
        sel["countries"] = v.countries
    if v.port_forwarding is not None:
        prov.setdefault("port_forwarding", {})["enabled"] = v.port_forwarding
    wg, ov = vpn.setdefault("wireguard", {}), vpn.setdefault("openvpn", {})
    if v.wireguard_private_key:
        wg["private_key"] = v.wireguard_private_key
    if v.wireguard_addresses is not None:
        wg["addresses"] = v.wireguard_addresses
    if v.openvpn_user:
        ov["user"] = v.openvpn_user
    if v.openvpn_password:
        ov["password"] = v.openvpn_password
    return doc


def _gluetun_headers() -> dict[str, str]:
    key = os.environ.get(GLUETUN_API_KEY_ENV, "")
    if not key:
        raise HTTPException(503, f"{GLUETUN_API_KEY_ENV} is not configured on this node (see deploy/gluetun-auth.toml)")
    return {"X-API-Key": key}


def _public_vpn_view(doc: dict) -> dict:
    vpn = doc.get("vpn", {})
    prov = vpn.get("provider", {})
    return {"provider": prov.get("name"), "type": vpn.get("type"),
            "countries": prov.get("server_selection", {}).get("countries"),
            "port_forwarding": prov.get("port_forwarding", {}).get("enabled"),
            "wireguard_private_key_set": bool(vpn.get("wireguard", {}).get("private_key")),
            "openvpn_user": vpn.get("openvpn", {}).get("user")}


@app.get("/vpn/settings")
def vpn_settings_get() -> dict:
    with httpx.Client(timeout=10) as http:
        try:
            r = http.get(f"{GLUETUN_URL}/v1/vpn/settings", headers=_gluetun_headers())
            r.raise_for_status()
            return _public_vpn_view(r.json())
        except httpx.HTTPError as e:
            raise HTTPException(502, f"gluetun settings API: {e}") from e


@app.put("/vpn/settings")
def vpn_settings_put(v: VpnSettings) -> dict:
    with httpx.Client(timeout=15) as http:
        try:
            h = _gluetun_headers()
            cur = http.get(f"{GLUETUN_URL}/v1/vpn/settings", headers=h)
            cur.raise_for_status()
            r = http.put(f"{GLUETUN_URL}/v1/vpn/settings", headers=h, json=merge_vpn(cur.json(), v))
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"gluetun rejected the settings ({e.response.status_code}): "
                                     f"{e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            raise HTTPException(502, f"gluetun settings API: {e}") from e
    return {"applied": True}
