"""Admin settings API. The app has a single user, who is the admin; every route needs the session."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import auth, settings_store as store
from ..config import settings
from ..db import get_db
from ..download import service

router = APIRouter(prefix="/api/app-settings", tags=["settings"])


class SettingsIn(BaseModel):
    values: dict[str, object] = {}
    clear: list[str] = []


def _side_effects(changed: list[str]) -> None:
    if any(k.startswith("telegram_") or k == "app_base_url" for k in changed):
        from ..notify import telegram
        telegram.start()  # bumps the generation: old poller exits, new one starts if enabled
    if any(k in changed for k in ("download_client", "qbit_username", "qbit_password", "node_agent_token")):
        service._qbit.clear()
        if "download_client" in changed:
            service._client = None


@router.get("")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return {"fields": store.describe(db)}


@router.put("")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)) -> dict:
    try:
        changed = store.save(db, store.Update(values=body.values, clear=body.clear))
    except store.SettingError as e:
        raise HTTPException(422, str(e)) from e
    _side_effects(changed)
    return {"changed": changed, "fields": store.describe(db)}


def _test_tmdb() -> str:
    if not settings.tmdb_api_key:
        raise RuntimeError("no TMDB API key saved")
    headers, params = {}, {}
    if settings.tmdb_api_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.tmdb_api_key}"
    else:
        params["api_key"] = settings.tmdb_api_key
    r = httpx.get("https://api.themoviedb.org/3/configuration", headers=headers, params=params, timeout=10)
    if r.status_code == 401:
        raise RuntimeError("TMDB rejected the key (401)")
    r.raise_for_status()
    return "TMDB key works"


def _test_jellyfin() -> str:
    if not (settings.jellyfin_url and settings.jellyfin_api_key):
        raise RuntimeError("Jellyfin URL and API key are both required")
    r = httpx.get(f"{settings.jellyfin_url.rstrip('/')}/System/Info",
                  headers={"X-Emby-Token": settings.jellyfin_api_key}, timeout=10)
    if r.status_code in (401, 403):
        raise RuntimeError("Jellyfin rejected the API key")
    r.raise_for_status()
    return f"Connected to Jellyfin {r.json().get('Version', '')}".strip()


def _test_telegram() -> str:
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        raise RuntimeError("bot token and chat ID are both required")
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    me = httpx.get(f"{base}/getMe", timeout=10)
    if me.status_code != 200:
        raise RuntimeError("Telegram rejected the bot token")
    sent = httpx.post(f"{base}/sendMessage", timeout=10, json={
        "chat_id": settings.telegram_chat_id, "text": "Media Fetcher: test message ✅"})
    if sent.status_code != 200:
        raise RuntimeError("token is valid but the message failed - press Start in the bot chat and check the chat ID")
    return f"Sent a test message as @{me.json()['result'].get('username', 'bot')}"


TESTS = {"tmdb": _test_tmdb, "jellyfin": _test_jellyfin, "telegram": _test_telegram}


@router.post("/test/{name}")
def run_test(name: str) -> dict:
    fn = TESTS.get(name)
    if fn is None:
        raise HTTPException(404, "unknown test")
    try:
        return {"ok": True, "message": fn()}
    except (RuntimeError, httpx.HTTPError) as e:
        return {"ok": False, "message": str(e)}


class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/password")
def change_password(body: PasswordIn, db: Session = Depends(get_db)) -> dict:
    if not auth.verify_password(body.current, settings.auth_password_hash or ""):
        raise HTTPException(403, "current password is incorrect")
    if len(body.new) < 10:
        raise HTTPException(422, "new password must be at least 10 characters")
    store.put(db, "auth_password_hash", auth.hash_password(body.new), secret=True)
    db.commit()
    store.apply_overrides(db)
    return {"ok": True}
