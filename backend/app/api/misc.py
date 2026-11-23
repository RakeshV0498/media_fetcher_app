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


@router.get("/nodes")
def nodes(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": n.id, "name": n.name, "agent_url": n.agent_url,
             "vpn": "n/a (arrives in step 6)", "public_ip": None}
            for n in db.scalars(select(Node))]
