from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from .api import releases, sources, tags
from .config import settings
from .db import SessionLocal
from .scanner import scheduler
from .seed import seed


def migrate() -> None:
    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    command.upgrade(Config(str(ini)), "head")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Path("data").mkdir(exist_ok=True)
    migrate()
    with SessionLocal() as db:
        seed(db)
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Media Fetcher", lifespan=lifespan)
app.include_router(sources.router)
app.include_router(tags.router)
app.include_router(releases.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "downloads_enabled": settings.downloads_enabled}
