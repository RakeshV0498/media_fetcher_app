from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Source
from ..scanner.discovery import discover_feed
from ..scanner.runner import make_client
from ..scanner.scheduler import schedule_source, scan_now

router = APIRouter(prefix="/api/sources", tags=["sources"])


class SourceIn(BaseModel):
    name: str
    url: str
    feed_url: str | None = None
    mode: str = "auto"
    selectors: dict[str, Any] = {}
    user_agent: str = ""
    interval_minutes: int = 60
    cron: str | None = None
    enabled: bool = True
    default_tag_id: int | None = None


    @field_validator("selectors")
    @classmethod
    def _check_selectors(cls, v: dict[str, Any]) -> dict[str, Any]:
        for key, val in v.items():
            if key == "detail":  # second-level (detail page) selectors: same keys, string values
                if not isinstance(val, dict) or not all(isinstance(x, str) for x in val.values()):
                    raise ValueError("'detail' must be an object of selector strings")
                if not val.get("item") or not val.get("title"):
                    raise ValueError("'detail' needs at least 'item' and 'title' selectors")
            elif not isinstance(val, str):
                raise ValueError(f"selector '{key}' must be a string")
        return v


class SourceOut(SourceIn):
    id: int
    last_status: str = ""

    model_config = {"from_attributes": True}


def _get(db: Session, sid: int) -> Source:
    src = db.get(Source, sid)
    if not src:
        raise HTTPException(404, "source not found")
    return src


@router.get("", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return list(db.scalars(select(Source).order_by(Source.id)))


@router.post("", response_model=SourceOut, status_code=201)
def create_source(body: SourceIn, db: Session = Depends(get_db)) -> Source:
    src = Source(**body.model_dump())
    db.add(src)
    db.commit()
    schedule_source(src)
    return src


@router.put("/{sid}", response_model=SourceOut)
def update_source(sid: int, body: SourceIn, db: Session = Depends(get_db)) -> Source:
    src = _get(db, sid)
    for k, v in body.model_dump().items():
        setattr(src, k, v)
    db.commit()
    schedule_source(src)
    return src


@router.delete("/{sid}", status_code=204)
def delete_source(sid: int, db: Session = Depends(get_db)) -> None:
    src = _get(db, sid)
    src.enabled = False
    schedule_source(src)
    db.delete(src)
    db.commit()


@router.post("/{sid}/scan")
def scan(sid: int, db: Session = Depends(get_db)) -> dict[str, str]:
    _get(db, sid)
    return {"status": scan_now(sid)}


@router.post("/discover")
def discover(url: str) -> dict[str, str | None]:
    class _S:
        user_agent = ""
    with make_client(_S()) as client:  # type: ignore[arg-type]
        return {"feed_url": discover_feed(client, url)}
