"""On-demand loading of a release's versions from its detail page (two-level sites)."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from ..models import Release, Source
from .html import fetch_html
from .runner import add_variant, make_client


def _same_host(a: str, b: str) -> bool:
    return (urlparse(a).hostname or "").lower() == (urlparse(b).hostname or "").lower() != ""


def load_versions(db: Session, rel: Release, client: httpx.Client | None = None) -> int:
    """Fetch rel.detail_url with the source's `detail` selectors and attach every version found.
    Only the source's own host is fetched, so a scraped link can never point the server at your LAN."""
    src = db.get(Source, rel.detail_source_id) if rel.detail_source_id else None
    cfg = (src.selectors or {}).get("detail") if src else None
    if not (src and cfg and rel.detail_url):
        raise ValueError("this entry has no detail page to load versions from")
    if not rel.detail_url.startswith(("http://", "https://")) or not _same_host(rel.detail_url, src.url):
        raise ValueError("refusing to fetch a detail page on a different site than the source")
    own = client is None
    client = client or make_client(src)
    try:
        items = fetch_html(client, rel.detail_url, cfg)
    finally:
        if own:
            client.close()
    if not items:
        raise ValueError("no versions were found on the detail page - check the source's 'detail' selectors")
    added = sum(add_variant(db, src, rel, i) for i in items)
    rel.details_loaded_at = datetime.now(timezone.utc)
    db.commit()
    return added
