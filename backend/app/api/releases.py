from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Release, Setting
from ..parsing.ranking import rank_variants

router = APIRouter(prefix="/api/releases", tags=["releases"])


@router.get("")
def list_releases(status: str = "new", all_variants: bool = False,
                  db: Session = Depends(get_db)) -> list[dict]:
    pref = db.get(Setting, "preferred_quality")
    quality = pref.value if pref else "1080p"
    out = []
    for r in db.scalars(select(Release).where(Release.status == status).order_by(Release.id.desc())):
        ranked = rank_variants(r.variants, quality, None if all_variants else 5)
        out.append({
            "id": r.id, "title": r.title, "year": r.year, "season": r.season,
            "episode": r.episode, "kind": r.kind, "suggested_tag_id": r.suggested_tag_id,
            "variant_count": len(r.variants),
            "variants": [{
                "id": v.id, "source_id": v.source_id, "quality": v.quality, "codec": v.codec,
                "size_bytes": v.size_bytes, "seeders": v.seeders, "leechers": v.leechers,
                "language": v.language, "title": v.title,
            } for v in ranked],
        })
    return out
