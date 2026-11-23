from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..download import service
from ..models import Download

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


@router.get("")
def list_downloads(db: Session = Depends(get_db)) -> list[dict]:
    client = service.get_client()
    out = []
    for d in service.list_downloads(db):
        p = client.status(d.client_id) if d.client_id else None
        if p and p.state != d.status:
            d.status = p.state
        out.append({
            "id": d.id, "title": d.release.title, "season": d.release.season,
            "episode": d.release.episode, "quality": d.variant.quality,
            "tag": d.tag.name, "node": d.node_name, "status": d.status,
            "progress": p.progress if p else (1.0 if d.status == "done" else 0.0),
            "speed": p.speed if p else 0, "eta": p.eta if p else None, "error": d.error, "files": d.final_files,
        })
    db.commit()
    return out


def _dl(db: Session, did: int) -> Download:
    d = db.get(Download, did)
    if not d:
        raise HTTPException(404, "download not found")
    return d


@router.post("/{did}/pause")
def pause(did: int, db: Session = Depends(get_db)) -> dict:
    d = _dl(db, did)
    service.get_client().pause(d.client_id)
    d.status = "paused"
    db.commit()
    return {"status": d.status}


@router.post("/{did}/resume")
def resume(did: int, db: Session = Depends(get_db)) -> dict:
    d = _dl(db, did)
    service.get_client().resume(d.client_id)
    d.status = "downloading"
    db.commit()
    return {"status": d.status}


@router.delete("/{did}", status_code=204)
def remove(did: int, db: Session = Depends(get_db)) -> None:
    d = _dl(db, did)
    service.get_client().remove(d.client_id)
    db.delete(d)
    db.commit()


@router.post("/{did}/retry")
def retry(did: int, db: Session = Depends(get_db)) -> dict:
    d = _dl(db, did)
    if d.status not in ("failed", "needs_attention", "duplicate"):
        raise HTTPException(409, f"nothing to retry (status {d.status})")
    service.finalize(db, d)
    return {"status": d.status, "error": d.error}


class SeasonIn(BaseModel):
    season: int
    episode: int | None = None


@router.post("/{did}/set-season")
def set_season(did: int, body: SeasonIn, db: Session = Depends(get_db)) -> dict:
    """Manual override for unresolved season (e.g. anime absolute numbering), then re-file."""
    d = _dl(db, did)
    d.release.season = body.season
    if body.episode is not None:
        d.release.episode = body.episode
    db.commit()
    service.finalize(db, d)
    return {"status": d.status, "error": d.error}
