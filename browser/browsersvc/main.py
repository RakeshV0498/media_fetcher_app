"""Optional render service: loads a page in a real (headless) Chromium and returns the HTML after JavaScript ran.

Deliberately plain: normal browser, the configured User-Agent, no stealth or fingerprint tricks. Bot-check pages are
reported (`blocked`) instead of being bypassed. One render at a time, a fresh context per request, hard limits.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import re
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .guard import UrlRefused, check_url, detect_block

MAX_HTML = 4_000_000
BLOCKED_TYPES = {"image", "media", "font"}
CHROMIUM = os.environ.get("CHROMIUM_PATH", "")  # e.g. /usr/bin/chromium; empty = Playwright's bundled browser
LAUNCH_ARGS = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]

_sem = asyncio.Semaphore(1)


def allow_private() -> bool:
    return os.environ.get("ALLOW_PRIVATE") == "1"


def auth(x_browser_token: str = Header(default="")) -> None:
    token = os.environ.get("BROWSER_TOKEN", "")
    if not token:
        raise HTTPException(503, "BROWSER_TOKEN is not configured on the browser service")
    if not hmac.compare_digest(x_browser_token, token):
        raise HTTPException(401, "bad token")


app = FastAPI(title="Media Fetcher browser service", dependencies=[Depends(auth)])


class RenderIn(BaseModel):
    url: str
    wait_selector: str | None = None
    wait_ms: int = Field(default=0, ge=0, le=15000)
    scroll: bool = False
    user_agent: str = ""
    timeout_s: int = Field(default=30, ge=5, le=120)


async def _launch(pw: Any):
    kw: dict[str, Any] = {"args": LAUNCH_ARGS, "headless": True}
    if CHROMIUM:
        kw["executable_path"] = CHROMIUM
    return await pw.chromium.launch(**kw)


async def render_page(req: RenderIn, playwright_factory=None) -> dict[str, Any]:
    from playwright.async_api import TimeoutError as PwTimeout
    from playwright.async_api import async_playwright
    factory = playwright_factory or async_playwright
    check_url(req.url, allow_private())
    seen_hosts: dict[str, bool] = {}

    async with factory() as pw:
        browser = await _launch(pw)
        try:
            ctx = await browser.new_context(user_agent=req.user_agent or None, viewport={"width": 1280, "height": 900})
            page = await ctx.new_page()

            async def gate(route):
                r = route.request
                if r.resource_type in BLOCKED_TYPES:
                    return await route.abort()
                host = re.sub(r"^\w+://([^/:]+).*$", r"\1", r.url)
                if host not in seen_hosts:  # sub-requests must not reach the LAN either
                    try:
                        check_url(r.url, allow_private())
                        seen_hosts[host] = True
                    except UrlRefused:
                        seen_hosts[host] = False
                return await (route.continue_() if seen_hosts[host] else route.abort())

            await page.route("**/*", gate)
            try:
                resp = await page.goto(req.url, wait_until="domcontentloaded", timeout=req.timeout_s * 1000)
                if req.wait_selector:
                    await page.wait_for_selector(req.wait_selector, timeout=req.timeout_s * 1000)
                else:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=min(8000, req.timeout_s * 1000))
                    except PwTimeout:
                        pass  # chatty pages never go idle; what has rendered by now is what we take
                if req.scroll:
                    for _ in range(6):
                        await page.mouse.wheel(0, 2500)
                        await page.wait_for_timeout(400)
                if req.wait_ms:
                    await page.wait_for_timeout(req.wait_ms)
                html = await page.content()
                title = await page.title()
                status = resp.status if resp else 0
                final_url = page.url
            except PwTimeout as e:
                raise HTTPException(504, f"the page did not finish loading in {req.timeout_s}s: {str(e)[:120]}") from e
        finally:
            await browser.close()
    check_url(final_url, allow_private())  # a redirect must not land on an internal address
    if len(html) > MAX_HTML:
        raise HTTPException(413, "the rendered page is too large")
    return {"html": html, "final_url": final_url, "status": status, "title": title,
            "blocked": detect_block(status, title, html)}


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/render")
async def render(req: RenderIn) -> dict[str, Any]:
    try:
        check_url(req.url, allow_private())
    except UrlRefused as e:
        raise HTTPException(400, str(e)) from e
    async with _sem:  # one page at a time keeps memory bounded on a Pi
        try:
            return await render_page(req)
        except UrlRefused as e:
            raise HTTPException(400, str(e)) from e
        except HTTPException:
            raise
        except Exception as e:  # browser crash, navigation error, DNS failure ...
            raise HTTPException(502, f"browser error: {str(e)[:200]}") from e


@app.get("/selftest")
async def selftest() -> dict[str, Any]:
    """Proves Chromium launches and runs JavaScript, using an inline page (no network)."""
    from playwright.async_api import async_playwright
    html = "<html><body><div id=x></div><script>document.getElementById('x').textContent='js-ok'</script></body></html>"
    async with _sem:
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    page = await (await browser.new_context()).new_page()
                    await page.set_content(html)
                    text = await page.inner_text("#x")
                    version = browser.version
                finally:
                    await browser.close()
        except Exception as e:
            raise HTTPException(502, f"browser failed to start: {str(e)[:200]}") from e
    if text != "js-ok":
        raise HTTPException(502, "browser started but JavaScript did not run")
    return {"ok": True, "chromium": version}
