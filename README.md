# Media Fetcher

Self-hosted release monitor with approval-based downloads for Jellyfin.
Controller (Pi 5) + a thin node agent on each Pi. Downloads are **disabled by default**
(`DOWNLOADS_ENABLED=false`) until the VPN layer is configured and verified.

Layout: `backend/` (FastAPI), `frontend/` (React), `node_agent/`, `deploy/`.

```
cp .env.example .env
cd backend && pip install -e '.[dev]' && pytest
```

You are responsible for only fetching content you are entitled to.
