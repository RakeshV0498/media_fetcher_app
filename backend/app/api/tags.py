from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Tag

router = APIRouter(prefix="/api/tags", tags=["tags"])


class TagIO(BaseModel):
    name: str
    kind: str
    node_id: int | None = None
    qbit_category: str = ""
    final_path: str = ""


class TagOut(TagIO):
    id: int
    model_config = {"from_attributes": True}


@router.get("", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.id)))


@router.put("/{tid}", response_model=TagOut)
def update_tag(tid: int, body: TagIO, db: Session = Depends(get_db)) -> Tag:
    tag = db.get(Tag, tid)
    if not tag:
        raise HTTPException(404, "tag not found")
    for k, v in body.model_dump().items():
        setattr(tag, k, v)
    db.commit()
    return tag
