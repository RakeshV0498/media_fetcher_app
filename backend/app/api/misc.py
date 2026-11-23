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
    max_concurrent: int = 2


def _node_status(n: Node) -> dict:
    from ..download import service
    info = {"vpn_ok": False, "vpn": "no node agent configured", "public_ip": None, "home_ip": None}
    agent = service.agent_for(n)
    if agent:
        v = agent.vpn(settings.home_public_ip)
        info = {"vpn_ok": v.gate.allowed, "vpn": "protected" if v.gate.allowed else v.gate.reason,
                "public_ip": v.vpn_ip, "home_ip": v.home_ip}
    return {"id": n.id, "name": n.name, "agent_url": n.agent_url, "qbit_url": n.qbit_url,
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
    db.commit()
    return _node_status(n)
