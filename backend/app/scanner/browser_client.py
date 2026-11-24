"""Client for the optional browser (JavaScript rendering) service. See browser/browsersvc/."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..config import settings

START_HINT = "start it with: docker compose -f deploy/docker-compose.yml --profile browser up -d --build"


class BrowserError(Exception):
    pass


class BrowserUnavailable(BrowserError):
    """Disabled in Settings, not running, or the token does not match."""


class BrowserBlocked(BrowserError):
    """The site showed a human-verification / bot-check page. We report it; we do not try to get around it."""


class BrowserTimeout(BrowserError):
    pass


@dataclass
class RenderedPage:
    html: str
    final_url: str
    status: int
    title: str


def _headers() -> dict[str, str]:
    return {"X-Browser-Token": settings.browser_token}


def render(url: str, *, wait_selector: str | None = None, user_agent: str = "", scroll: bool = False,
           client: httpx.Client | None = None) -> RenderedPage:
    if not settings.browser_enabled:
        raise BrowserUnavailable("Browser rendering is turned off. Enable it in Settings → Integrations "
                                 f"(and the service must be running: {START_HINT}).")
    own = client is None
    client = client or httpx.Client(timeout=settings.browser_timeout_s + 15)
    try:
        r = client.post(f"{settings.browser_url.rstrip('/')}/render", headers=_headers(), json={
            "url": url, "wait_selector": wait_selector or None, "scroll": scroll,
            "user_agent": user_agent or settings.user_agent, "timeout_s": settings.browser_timeout_s})
    except httpx.TimeoutException as e:
        raise BrowserTimeout("the browser service did not answer in time") from e
    except httpx.HTTPError as e:
        raise BrowserUnavailable(f"cannot reach the browser service at {settings.browser_url} ({START_HINT})") from e
    finally:
        if own:
            client.close()
    if r.status_code in (401, 503):
        raise BrowserUnavailable("the browser service rejected the token: 'Browser token' in Settings must equal "
                                 "BROWSER_TOKEN in the controller's .env")
    if r.status_code == 504:
        raise BrowserTimeout(_detail(r))
    if r.status_code != 200:
        raise BrowserError(_detail(r))
    d = r.json()
    if d.get("blocked"):
        raise BrowserBlocked(f"{d['blocked']}. Open the page in your own browser and use 'Paste page HTML' instead.")
    return RenderedPage(html=d["html"], final_url=d.get("final_url") or url, status=int(d.get("status") or 0),
                        title=d.get("title") or "")


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail", f"browser service error {r.status_code}"))
    except ValueError:
        return f"browser service error {r.status_code}"
