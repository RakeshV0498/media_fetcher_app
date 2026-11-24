from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Literal

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
    render: Literal["static", "browser"] = "static"
    wait_selector: str | None = None

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


class AnalyzeIn(BaseModel):
    kind: str = "listing"  # listing | detail
    url: str | None = None
    html: str | None = None  # pasted page source (for sites that block scrapers, need a login or JavaScript)
    site_url: str | None = None  # the source's listing URL; a detail URL must be on the same host
    user_agent: str = ""


MAX_PAGE_BYTES = 4_000_000


@router.post("/analyze")
def analyze_page(body: AnalyzeIn) -> dict:
    """Propose selector configs for a page (auto-detect). Nothing is saved; the UI shows previews to pick from."""
    from urllib.parse import urlparse

    import httpx

    from ..config import settings
    from ..scanner.analyze import analyze_detail, analyze_listing
    if body.kind not in ("listing", "detail"):
        raise HTTPException(422, "kind must be 'listing' or 'detail'")
    html, base = body.html, body.url or body.site_url or ""
    if not html:
        if not body.url or not body.url.startswith(("http://", "https://")):
            raise HTTPException(422, "give a page URL (http/https) or paste the page HTML")
        if body.kind == "detail" and body.site_url and (urlparse(body.url).hostname or "") != (urlparse(body.site_url).hostname or ""):
            raise HTTPException(400, "the detail page must be on the same site as the source")
        try:
            with httpx.Client(headers={"User-Agent": body.user_agent or settings.user_agent}, timeout=20,
                              follow_redirects=True) as c:
                r = c.get(body.url)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            hint = (" The site is probably blocking automated access: open it in your browser, save/copy the page source "
                    "and use 'Paste page HTML'." if e.response.status_code in (401, 403, 429, 503) else "")
            raise HTTPException(502, f"the site answered HTTP {e.response.status_code}.{hint}") from e
        except httpx.HTTPError as e:
            raise HTTPException(502, f"could not fetch the page: {e}") from e
        if len(r.content) > MAX_PAGE_BYTES:
            raise HTTPException(413, "that page is too large to analyze")
        html = r.text
    if len(html) > MAX_PAGE_BYTES:
        raise HTTPException(413, "that page is too large to analyze")
    cands, warnings = (analyze_detail if body.kind == "detail" else analyze_listing)(html, base)
    return {"candidates": [c.as_dict() for c in cands], "warnings": warnings, "kind": body.kind}


@router.post("/discover")
def discover(url: str) -> dict[str, str | None]:
    class _S:
        user_agent = ""
    with make_client(_S()) as client:  # type: ignore[arg-type]
        return {"feed_url": discover_feed(client, url)}
