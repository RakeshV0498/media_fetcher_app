from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import auth as auth_api
from .api import app_settings, downloads, misc, releases, sources, tags
from .auth import require_user
from .config import settings
from .db import SessionLocal
from .notify import telegram
from .scanner import scheduler
from . import settings_store
from .seed import seed


def migrate() -> None:
    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    command.upgrade(Config(str(ini)), "head")


def _enrich_and_notify() -> None:
    import httpx

    from .parsing.enrich import enrich_pending
    with SessionLocal() as db:
        enrich_pending(db)
        with httpx.Client(timeout=15) as http:
            telegram.notify_new(db, http)


def _process_completed() -> None:
    from .download import service
    with SessionLocal() as db:
        service.process_completed(db)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Path("data").mkdir(exist_ok=True)
    migrate()
    with SessionLocal() as db:
        seed(db)
        settings_store.apply_overrides(db)
    scheduler.start()
    scheduler.scheduler.add_job(releases.unsnooze_due, "interval", minutes=5,
                                id="unsnooze", replace_existing=True)
    scheduler.scheduler.add_job(_process_completed, "interval", seconds=30,
                                id="postprocess", replace_existing=True, max_instances=1)
    scheduler.scheduler.add_job(_enrich_and_notify, "interval", minutes=1,
                                id="enrich", replace_existing=True, max_instances=1)
    telegram.start()
    yield
    telegram.stop()
    scheduler.stop()


app = FastAPI(title="Media Fetcher", lifespan=lifespan)
app.include_router(auth_api.router)
_protected = [Depends(require_user)]
for _r in (app_settings.router, sources.router, tags.router, releases.router, downloads.router, misc.router):
    app.include_router(_r, dependencies=_protected)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "downloads_enabled": settings.downloads_enabled}


DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
