from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..download import service
from ..models import Release, Variant
from ..parsing.ranking import rank_variants

router = APIRouter(prefix="/api/releases", tags=["releases"])


def _card(r: Release, quality: str, all_variants: bool) -> dict:
    ranked = rank_variants(r.variants, quality, None if all_variants else 5)
    return {
        "id": r.id, "title": r.title, "year": r.year, "season": r.season,
        "episode": r.episode, "absolute_episode": r.absolute_episode, "kind": r.kind,
        "status": r.status, "suggested_tag_id": r.suggested_tag_id,
        "variant_count": len(r.variants),
        "variants": [{
            "id": v.id, "source_id": v.source_id, "quality": v.quality, "codec": v.codec,
            "size_bytes": v.size_bytes, "seeders": v.seeders, "leechers": v.leechers,
            "language": v.language, "title": v.title,
        } for v in ranked],
    }


@router.get("")
def list_releases(status: str = "new", tag_id: int | None = None, source_id: int | None = None,
                  kind: str | None = None, q: str | None = None, all_variants: bool = False,
                  db: Session = Depends(get_db)) -> list[dict]:
    quality = service.preferred_quality(db)
    stmt = select(Release).where(Release.status == status).order_by(Release.id.desc())
    if tag_id is not None:
        stmt = stmt.where(Release.suggested_tag_id == tag_id)
    if kind:
        stmt = stmt.where(Release.kind == kind)
    if q:
        stmt = stmt.where(Release.title.ilike(f"%{q}%"))
    if source_id is not None:
        stmt = stmt.where(Release.variants.any(Variant.source_id == source_id))
    return [_card(r, quality, all_variants) for r in db.scalars(stmt)]


class ApproveIn(BaseModel):
    variant_id: int
    tag_id: int


def _approve(db: Session, rid: int, variant_id: int, tag_id: int) -> dict:
    try:
        dl = service.approve(db, rid, variant_id, tag_id)
    except service.ApproveError as e:
        raise HTTPException(e.status, e.message) from e
    return {"download_id": dl.id, "status": dl.status}


@router.post("/{rid}/approve")
def approve(rid: int, body: ApproveIn, db: Session = Depends(get_db)) -> dict:
    return _approve(db, rid, body.variant_id, body.tag_id)


def _get(db: Session, rid: int) -> Release:
    r = db.get(Release, rid)
    if not r:
        raise HTTPException(404, "release not found")
    return r


@router.post("/{rid}/reject")
def reject(rid: int, db: Session = Depends(get_db)) -> dict:
    _get(db, rid).status = "rejected"
    db.commit()
    return {"status": "rejected"}


class SnoozeIn(BaseModel):
    hours: int = 24


@router.post("/{rid}/snooze")
def snooze(rid: int, body: SnoozeIn, db: Session = Depends(get_db)) -> dict:
    r = _get(db, rid)
    r.status = "snoozed"
    r.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=body.hours)
    db.commit()
    return {"status": "snoozed"}


class BulkIn(BaseModel):
    ids: list[int]
    action: str  # approve | reject | snooze
    tag_id: int | None = None
    hours: int = 24


@router.post("/bulk")
def bulk(body: BulkIn, db: Session = Depends(get_db)) -> dict:
    done: list[int] = []
    skipped: dict[int, str] = {}
    for rid in body.ids:
        r = db.get(Release, rid)
        if not r:
            skipped[rid] = "not found"
        elif body.action == "reject":
            r.status = "rejected"
            done.append(rid)
        elif body.action == "snooze":
            r.status = "snoozed"
            r.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=body.hours)
            done.append(rid)
        elif body.action == "approve":
            tag_id = body.tag_id or r.suggested_tag_id
            var = service.best_variant(db, r)
            if not tag_id or not var:
                skipped[rid] = "no tag or no variant at preferred quality"
                continue
            try:
                service.approve(db, rid, var.id, tag_id)
                done.append(rid)
            except service.ApproveError as e:
                skipped[rid] = e.message
        else:
            raise HTTPException(400, "unknown action")
    db.commit()
    return {"done": done, "skipped": skipped}


def unsnooze_due() -> None:
    from ..db import SessionLocal
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        for r in db.scalars(select(Release).where(Release.status == "snoozed")):
            if r.snoozed_until and r.snoozed_until.replace(tzinfo=timezone.utc) <= now:
                r.status, r.snoozed_until = "new", None
        db.commit()
