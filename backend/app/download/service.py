from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Download, Release, Setting, Tag, Variant
from ..parsing.ranking import rank_variants
from .client import DownloadClient
from .gate import check_gate
from .mock import MockClient

_client: DownloadClient | None = None


def get_client() -> DownloadClient:
    global _client
    if _client is None:
        if settings.download_client == "mock":
            _client = MockClient()
        else:
            raise NotImplementedError("qbittorrent client arrives in step 6")
    return _client


def vpn_ok(_tag: Tag) -> bool:
    return settings.vpn_ok_override  # real per-node health check lands in step 6


class ApproveError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def preferred_quality(db: Session) -> str:
    s = db.get(Setting, "preferred_quality")
    return s.value if s else "1080p"


def approve(db: Session, release_id: int, variant_id: int, tag_id: int,
            client: DownloadClient | None = None) -> Download:
    client = client or get_client()
    rel = db.get(Release, release_id)
    var = db.get(Variant, variant_id)
    tag = db.get(Tag, tag_id)
    if not rel or not var or not tag:
        raise ApproveError(404, "release, variant or tag not found")
    if var.release_id != rel.id:
        raise ApproveError(400, "variant does not belong to this release")
    if rel.status not in ("new", "snoozed"):
        raise ApproveError(409, f"release is already {rel.status}")
    gate = check_gate(settings.downloads_enabled, vpn_ok(tag), client.is_mock)
    if not gate.allowed:
        raise ApproveError(409, gate.reason)
    uri = var.magnet or var.torrent_url or var.link
    if not uri:
        raise ApproveError(400, "variant has no magnet or torrent link")
    cid = client.add(uri, tag.qbit_category, tag.final_path)
    dl = Download(release_id=rel.id, variant_id=var.id, tag_id=tag.id,
                  node_name=tag.node.name if tag.node else "", client_id=cid, status="downloading")
    rel.status = "approved"
    rel.suggested_tag_id = tag.id
    db.add(dl)
    db.commit()
    return dl


def best_variant(db: Session, rel: Release) -> Variant | None:
    ranked = rank_variants(rel.variants, preferred_quality(db), None)
    pref = preferred_quality(db)
    for v in ranked:
        if v.quality == pref:
            return v
    return None


def list_downloads(db: Session) -> list[Download]:
    return list(db.scalars(select(Download).order_by(Download.id.desc())))
