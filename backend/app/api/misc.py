from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..download import service
from ..models import Node, Setting

router = APIRouter(prefix="/api", tags=["misc"])


class SettingsIO(BaseModel):
    preferred_quality: str


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return {"preferred_quality": service.preferred_quality(db),
            "downloads_enabled": settings.downloads_enabled,
            "download_client": settings.download_client}


@router.put("/settings")
def put_settings(body: SettingsIO, db: Session = Depends(get_db)) -> dict:
    s = db.get(Setting, "preferred_quality") or Setting(key="preferred_quality")
    s.value = body.preferred_quality
    db.add(s)
    db.commit()
    return {"preferred_quality": s.value}


class NodeIn(BaseModel):
    agent_url: str = ""
    qbit_url: str = ""
    download_dir: str = ""
    max_concurrent: int = 2


def _node_status(n: Node) -> dict:
    from ..download import service
    info = {"vpn_ok": False, "vpn": "no node agent configured", "public_ip": None, "home_ip": None}
    agent = service.agent_for(n)
    if agent:
        v = agent.vpn(settings.home_public_ip)
        info = {"vpn_ok": v.gate.allowed, "vpn": "protected" if v.gate.allowed else v.gate.reason,
                "public_ip": v.vpn_ip, "home_ip": v.home_ip}
    info["vpn_required"] = settings.require_vpn
    return {"id": n.id, "name": n.name, "agent_url": n.agent_url, "qbit_url": n.qbit_url, "download_dir": n.download_dir,
            "max_concurrent": n.max_concurrent, **info}


@router.get("/nodes")
def nodes(db: Session = Depends(get_db)) -> list[dict]:
    return [_node_status(n) for n in db.scalars(select(Node).order_by(Node.id))]


@router.put("/nodes/{nid}")
def update_node(nid: int, body: NodeIn, db: Session = Depends(get_db)) -> dict:
    from fastapi import HTTPException
    n = db.get(Node, nid)
    if not n:
        raise HTTPException(404, "node not found")
    n.agent_url, n.qbit_url, n.max_concurrent = body.agent_url, body.qbit_url, max(1, body.max_concurrent)
    n.download_dir = body.download_dir.strip()
    db.commit()
    return _node_status(n)


# ---------------- folder browsing, VPN settings, connection tests (per node) ----------------
from pathlib import Path  # noqa: E402

from .. import settings_store as store  # noqa: E402
from ..download.agent import AgentError  # noqa: E402
from ..postprocess import browse as fsbrowse  # noqa: E402
from ..postprocess.mover import PathNotAllowed  # noqa: E402


def _node(db: Session, nid: int) -> Node:
    from fastapi import HTTPException
    n = db.get(Node, nid)
    if not n:
        raise HTTPException(404, "node not found")
    return n


def _local_roots() -> list[Path]:
    return [Path(r.strip()) for r in settings.media_roots.split(",") if r.strip()]


def _fs_call(n: Node, op: str, arg: str) -> dict:
    from fastapi import HTTPException

    from ..download import service
    agent = service.agent_for(n)
    try:
        if agent is not None:
            return agent.browse(arg) if op == "browse" else agent.mkdir(arg)
        roots = _local_roots()
        return fsbrowse.browse(arg, roots) if op == "browse" else fsbrowse.make_dir(arg, roots)
    except (AgentError, PathNotAllowed, NotADirectoryError) as e:
        raise HTTPException(400, str(e)) from e


@router.get("/nodes/{nid}/browse")
def node_browse(nid: int, path: str = "", db: Session = Depends(get_db)) -> dict:
    return _fs_call(_node(db, nid), "browse", path)


class MkDirIn(BaseModel):
    path: str


@router.post("/nodes/{nid}/mkdir")
def node_mkdir(nid: int, body: MkDirIn, db: Session = Depends(get_db)) -> dict:
    return _fs_call(_node(db, nid), "mkdir", body.path)


VPN_FIELDS = (("provider", False), ("type", False), ("countries", False), ("port_forwarding", False),
              ("wireguard_addresses", False), ("wireguard_private_key", True),
              ("openvpn_user", False), ("openvpn_password", True))


class VpnIn(BaseModel):
    provider: str = ""
    type: str = "wireguard"
    countries: str = ""  # comma separated
    port_forwarding: bool = False
    wireguard_addresses: str = ""
    wireguard_private_key: str = ""  # blank = keep saved
    openvpn_user: str = ""
    openvpn_password: str = ""  # blank = keep saved
    apply: bool = False


def _vpn_view(db: Session, n: Node) -> dict:
    out: dict = {}
    for name, secret in VPN_FIELDS:
        key = f"vpn.{n.name}.{name}"
        if secret:
            out[f"{name}_set"] = store.is_set(db, key)
        else:
            v = store.get(db, key)
            out[name] = (v == "true") if name == "port_forwarding" else (v or ("wireguard" if name == "type" else ""))
    return out


@router.get("/nodes/{nid}/vpn")
def vpn_get(nid: int, db: Session = Depends(get_db)) -> dict:
    return _vpn_view(db, _node(db, nid))


def _csv(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


@router.put("/nodes/{nid}/vpn")
def vpn_put(nid: int, body: VpnIn, db: Session = Depends(get_db)) -> dict:
    from fastapi import HTTPException

    from ..download import service
    n = _node(db, nid)
    if body.type not in ("wireguard", "openvpn"):
        raise HTTPException(422, "type must be wireguard or openvpn")
    vals = body.model_dump()
    for name, secret in VPN_FIELDS:
        v = vals[name]
        if secret and not v:
            continue  # keep the saved secret
        store.put(db, f"vpn.{n.name}.{name}", "true" if v is True else "false" if v is False else str(v), secret=secret)
    db.commit()
    result: dict = {"saved": True, "applied": False, "message": "Saved."}
    if body.apply:
        agent = service.agent_for(n)
        if agent is None:
            raise HTTPException(409, "no node agent configured for this node - saved but not applied")
        payload: dict = {"provider": store.get(db, f"vpn.{n.name}.provider") or None,
                         "type": store.get(db, f"vpn.{n.name}.type") or None,
                         "countries": _csv(store.get(db, f"vpn.{n.name}.countries") or ""),
                         "port_forwarding": store.get(db, f"vpn.{n.name}.port_forwarding") == "true",
                         "wireguard_addresses": _csv(store.get(db, f"vpn.{n.name}.wireguard_addresses") or ""),
                         "wireguard_private_key": store.get(db, f"vpn.{n.name}.wireguard_private_key") or None,
                         "openvpn_user": store.get(db, f"vpn.{n.name}.openvpn_user") or None,
                         "openvpn_password": store.get(db, f"vpn.{n.name}.openvpn_password") or None}
        try:
            agent.vpn_settings_apply(payload)
            result.update(applied=True, message="Saved and sent to gluetun. Re-check the node in a few seconds.")
        except AgentError as e:
            result.update(message=f"Saved, but applying failed: {e}")
    return result | {"settings": _vpn_view(db, n)}


@router.post("/nodes/{nid}/test")
def node_test(nid: int, db: Session = Depends(get_db)) -> dict:
    from ..download import service
    from ..download.qbittorrent import QBittorrentClient
    n = _node(db, nid)
    checks = []
    agent = service.agent_for(n)
    if agent is None:
        checks.append({"name": "Node agent", "ok": False, "message": "no agent URL configured"})
    else:
        v = agent.vpn(settings.home_public_ip)
        checks.append({"name": "Node agent + VPN", "ok": v.gate.allowed,
                       "message": "reachable, VPN protected" if v.gate.allowed else v.gate.reason})
    if not n.qbit_url:
        checks.append({"name": "qBittorrent", "ok": False, "message": "no WebUI URL configured"})
    else:
        try:
            QBittorrentClient(n.qbit_url, settings.qbit_username, settings.qbit_password)._login()
            checks.append({"name": "qBittorrent", "ok": True, "message": "logged in"})
        except Exception as e:  # network error or bad credentials
            checks.append({"name": "qBittorrent", "ok": False, "message": str(e)[:200]})
    return {"checks": checks}
