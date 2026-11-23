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


# ---- post-processing -------------------------------------------------------
from pathlib import Path  # noqa: E402

from ..postprocess.jellyfin import refresh_library  # noqa: E402
from ..postprocess.mover import NeedsAttention, PathNotAllowed, cleanup_empty, file_release  # noqa: E402


def finalize(db: Session, dl: Download, client: DownloadClient | None = None,
             allowed_roots: list[Path] | None = None) -> Download:
    """Stop (no seeding), file into the Jellyfin layout, refresh Jellyfin. Safe to retry."""
    client = client or get_client()
    tag, rel = dl.tag, dl.release
    if allowed_roots is None and settings.media_roots:
        allowed_roots = [Path(r) for r in settings.media_roots.split(",") if r.strip()]
    if not dl.content_path:
        p = client.status(dl.client_id)
        if p and p.content_path:
            dl.content_path = p.content_path
    if not dl.content_path:
        dl.status = "done"  # mock/no files to file
        db.commit()
        return dl
    dl.status, dl.error = "moving", ""
    db.commit()
    if dl.client_id:  # stop + drop from client, keep files; never seed
        try:
            client.remove(dl.client_id, delete_files=False)
        except Exception:  # already gone is fine
            pass
        dl.client_id = ""
    try:
        res = file_release(Path(dl.content_path), Path(tag.final_path), rel.kind, rel.title,
                           rel.year, rel.season, rel.episode, allowed_roots)
        if res.duplicates:
            dl.status = "duplicate"
            dl.error = f"already in library: {', '.join(p.name for p in res.duplicates)}"
        else:
            dl.status = "done"
            dl.final_files = [str(d) for _, d in res.moved]
            cleanup_empty(Path(dl.content_path))
            refresh_library(settings.jellyfin_url, settings.jellyfin_api_key)
    except NeedsAttention as e:
        dl.status, dl.error = "needs_attention", str(e)
    except (PathNotAllowed, OSError) as e:
        dl.status, dl.error = "failed", str(e)
    db.commit()
    return dl


def process_completed(db: Session, client: DownloadClient | None = None) -> int:
    """Scheduler hook: finalize downloads the client reports as done."""
    client = client or get_client()
    n = 0
    for dl in db.scalars(select(Download).where(Download.status.in_(("downloading", "queued")))):
        p = client.status(dl.client_id) if dl.client_id else None
        if p and p.state == "done":
            finalize(db, dl, client)
            n += 1
    return n
