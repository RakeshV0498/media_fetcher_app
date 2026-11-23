from fastapi import FastAPI

from .config import settings

app = FastAPI(title="Media Fetcher")


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "downloads_enabled": settings.downloads_enabled}
