"""Optional Telegram bot (feature flag TELEGRAM_ENABLED). Long-polls the Bot API; LAN-friendly."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from html import escape

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..download import service
from ..models import Release, Tag
from ..parsing.ranking import rank_variants

API = "https://api.telegram.org/bot{token}/{method}"
MAX_PER_RUN = 10


def _call(http: httpx.Client, method: str, **payload: object) -> dict:
    r = http.post(API.format(token=settings.telegram_bot_token, method=method), json=payload, timeout=40)
    r.raise_for_status()
    return r.json()


def _size(b: int | None) -> str:
    return "?" if b is None else f"{b / 1e9:.1f}GB" if b >= 1e9 else f"{round(b / 1e6)}MB"


def build_message(db: Session, rel: Release) -> tuple[str, dict]:
    ep = f" S{rel.season:02d}E{rel.episode:02d}" if rel.season is not None and rel.episode is not None else (
        f" ep {rel.absolute_episode}" if rel.absolute_episode else "")
    tag = db.get(Tag, rel.suggested_tag_id) if rel.suggested_tag_id else None
    lines = [f"<b>{escape(rel.title)}</b> {rel.year or ''}{ep}",
             f"Suggested: {escape(tag.name) if tag else 'none - set a tag in the web UI'}"]
    if rel.overview:
        lines.append(escape(rel.overview[:200]))
    if settings.app_base_url:
        lines.append(settings.app_base_url)
    variants = rank_variants(rel.variants, service.preferred_quality(db), 5)
    rows = [[{"text": f"{v.quality or '?'} · {_size(v.size_bytes)} · ▲{v.seeders if v.seeders is not None else '-'}",
              "callback_data": f"a:{rel.id}:{v.id}"}] for v in variants]
    rows.append([{"text": "Reject", "callback_data": f"r:{rel.id}"}])
    return "\n".join(lines), {"inline_keyboard": rows}


def notify_new(db: Session, http: httpx.Client) -> int:
    if not (settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id):
        return 0
    sent = 0
    stmt = select(Release).where(Release.status == "new", Release.notified_at.is_(None)).limit(MAX_PER_RUN)
    for rel in db.scalars(stmt):
        if not rel.variants:
            continue
        text, markup = build_message(db, rel)
        try:
            _call(http, "sendMessage", chat_id=settings.telegram_chat_id, text=text,
                  parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        except httpx.HTTPError:
            break  # retry next run
        rel.notified_at = datetime.now(timezone.utc)
        db.commit()
        sent += 1
    return sent


def handle_callback(db: Session, data: str, chat_id: str | int) -> str:
    """Returns the toast text. Only the configured chat may act; approve uses the same gate as the UI."""
    if str(chat_id) != str(settings.telegram_chat_id):
        return "Not authorized"
    parts = data.split(":")
    try:
        if parts[0] == "a" and len(parts) == 3:
            rid, vid = int(parts[1]), int(parts[2])
            rel = db.get(Release, rid)
            if rel is None or not rel.suggested_tag_id:
                return "Pick a tag in the web UI first"
            service.approve(db, rid, vid, rel.suggested_tag_id)
            return "Approved"
        if parts[0] == "r" and len(parts) == 2:
            rel = db.get(Release, int(parts[1]))
            if rel is None:
                return "Not found"
            rel.status = "rejected"
            db.commit()
            return "Rejected"
    except service.ApproveError as e:
        return f"Blocked: {e.message}"
    except (ValueError, IndexError):
        pass
    return "Unknown action"


def process_update(db: Session, http: httpx.Client, update: dict) -> None:
    cb = update.get("callback_query")
    if not cb:
        return
    chat_id = (cb.get("message") or {}).get("chat", {}).get("id", cb.get("from", {}).get("id"))
    text = handle_callback(db, cb.get("data", ""), chat_id)
    _call(http, "answerCallbackQuery", callback_query_id=cb["id"], text=text)
    if text in ("Approved", "Rejected") and cb.get("message"):
        _call(http, "editMessageReplyMarkup", chat_id=chat_id,
              message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})


_stop = threading.Event()


def poll_loop() -> None:
    offset = 0
    with httpx.Client() as http:
        while not _stop.is_set():
            try:
                res = _call(http, "getUpdates", offset=offset, timeout=25, allowed_updates=["callback_query"])
                for u in res.get("result", []):
                    offset = u["update_id"] + 1
                    with SessionLocal() as db:
                        process_update(db, http, u)
            except httpx.HTTPError:
                _stop.wait(10)


def start() -> None:
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        _stop.clear()
        threading.Thread(target=poll_loop, daemon=True, name="telegram").start()


def stop() -> None:
    _stop.set()
