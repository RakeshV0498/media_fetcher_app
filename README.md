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

## Post-processing
Finished torrents are stopped (never seeded), then filed as
`Movies: Title (Year)/Title (Year).ext` and `TV/Anime: Show/Season NN/Show - SNNEENN.ext`
under the tag's final folder, and Jellyfin is refreshed. An existing show folder is reused.
Unknown season (e.g. anime absolute numbers) -> *needs attention*: set the season in the
Downloads page and it is filed; existing files are never overwritten (*duplicate*).
