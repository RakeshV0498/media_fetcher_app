from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Download, Release, Setting, Tag, Variant
from ..parsing.ranking import rank_variants
from ..models import Node
from .agent import AgentClient, AgentError
from .client import DownloadClient
from .gate import GateResult, check_gate, enough_space
from .mock import MockClient
from .qbittorrent import QBittorrentClient

_client: DownloadClient | None = None  # mock-mode singleton (tests may inject a client here)
_qbit: dict[str, DownloadClient] = {}


def get_client(node: Node | None = None) -> DownloadClient:
    global _client
    if _client is not None:
        return _client
    if settings.download_client == "mock":
        _client = MockClient()
        return _client
    if node is None or not node.qbit_url:
        raise RuntimeError(f"no qBittorrent URL configured for node {node.name if node else '?'}")
    key = f"{node.name}|{node.qbit_url}"
    if key not in _qbit:
        _qbit[key] = QBittorrentClient(node.qbit_url, settings.qbit_username, settings.qbit_password,
                                       max_active=node.max_concurrent)
    return _qbit[key]


def agent_for(node: Node | None) -> AgentClient | None:
    return AgentClient(node.agent_url) if node and node.agent_url else None


def vpn_gate(node: Node | None) -> GateResult:
    agent = agent_for(node)
    if agent is None:
        return GateResult(False, f"VPN health check failed: no node agent configured for "
                                 f"{node.name if node else 'this tag'} (cannot verify the VPN)")
    return agent.vpn(settings.home_public_ip).gate


class ApproveError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def preferred_quality(db: Session) -> str:
    s = db.get(Setting, "preferred_quality")
    return s.value if s else "1080p"


def approve(db: Session, release_id: int, variant_id: int, tag_id: int,
            client: DownloadClient | None = None) -> Download:
    rel = db.get(Release, release_id)
    var = db.get(Variant, variant_id)
    tag = db.get(Tag, tag_id)
    if not rel or not var or not tag:
        raise ApproveError(404, "release, variant or tag not found")
    client = client or get_client(tag.node)
    if var.release_id != rel.id:
        raise ApproveError(400, "variant does not belong to this release")
    if rel.status not in ("new", "snoozed"):
        raise ApproveError(409, f"release is already {rel.status}")
    # Gate order matters: the (network) VPN check only runs once the flag is on.
    gate = check_gate(settings.downloads_enabled,
                      GateResult(True) if (client.is_mock or not settings.downloads_enabled) else vpn_gate(tag.node),
                      client.is_mock)
    if not gate.allowed:
        raise ApproveError(409, gate.reason)
    if not client.is_mock:
        try:
            free = agent_for(tag.node).free_bytes(tag.final_path)  # type: ignore[union-attr]
        except AgentError as e:
            raise ApproveError(409, f"disk space check failed: {e}") from e
        space = enough_space(free, var.size_bytes, settings.min_free_reserve_gb * 1024**3)
        if not space.allowed:
            raise ApproveError(409, space.reason)
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
    tag, rel = dl.tag, dl.release
    client = client or get_client(tag.node)
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
    if rel.kind == "tv" and rel.season is None:
        try:  # last chance to resolve absolute numbering automatically
            import httpx

            from ..parsing.enrich import enrich_release
            with httpx.Client(timeout=15) as http:
                enrich_release(db, rel, http)
        except Exception:
            pass
    dl.status, dl.error = "moving", ""
    db.commit()
    if dl.client_id:  # stop + drop from client, keep files; never seed
        try:
            client.remove(dl.client_id, delete_files=False)
        except Exception:  # already gone is fine
            pass
        dl.client_id = ""
    try:
        agent = agent_for(tag.node)
        if agent is not None:  # files live on that Pi's disks: let its agent move them
            res = agent.postprocess(dl.content_path, tag.final_path, rel.kind, rel.title,
                                    rel.year, rel.season, rel.episode)
        else:
            res = file_release(Path(dl.content_path), Path(tag.final_path), rel.kind, rel.title,
                               rel.year, rel.season, rel.episode, allowed_roots)
        if res.duplicates:
            dl.status = "duplicate"
            dl.error = f"already in library: {', '.join(p.name for p in res.duplicates)}"
        else:
            dl.status = "done"
            dl.final_files = [str(d) for _, d in res.moved]
            if agent is None:
                cleanup_empty(Path(dl.content_path))
            refresh_library(settings.jellyfin_url, settings.jellyfin_api_key)
    except NeedsAttention as e:
        dl.status, dl.error = "needs_attention", str(e)
    except (PathNotAllowed, OSError, AgentError) as e:
        dl.status, dl.error = "failed", str(e)
    db.commit()
    return dl


def process_completed(db: Session, client: DownloadClient | None = None) -> int:
    """Scheduler hook: finalize downloads the client reports as done."""
    n = 0
    for dl in db.scalars(select(Download).where(Download.status.in_(("downloading", "queued")))):
        try:
            c = client or get_client(dl.tag.node)
            p = c.status(dl.client_id) if dl.client_id else None
            if p and p.state == "done":
                finalize(db, dl, c)
                n += 1
            elif p and p.state == "failed":
                dl.status, dl.error = "failed", "download client reported an error"
                db.commit()
        except Exception as e:  # one unreachable node must not block the others
            dl.error = f"client unreachable: {e}"[:200]
            db.commit()
    return n
