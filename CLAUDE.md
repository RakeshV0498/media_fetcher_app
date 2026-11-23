# Media Fetcher - project notes for Claude

Self-hosted release monitor + approval-based downloader that files into Jellyfin libraries.
Controller (FastAPI + SQLite + React) runs on the Pi 5; each Pi (5 and 4) runs a node stack (qBittorrent + thin agent).

## Decisions made by the owner (do not re-litigate)
- **VPN is OPTIONAL.** Downloads must work without a VPN. `require_vpn` defaults to false; gluetun/VPN is an opt-in
  extra (`docker-compose.node.yml`), the no-VPN stack is `docker-compose.node.novpn.yml`. Never make a VPN mandatory.
- `DOWNLOADS_ENABLED` is still the master switch (off by default); a real download also needs a node agent
  (disk checks + filing). `DOWNLOAD_CLIENT=mock` simulates downloads and touches nothing.
- **Library folders (real paths):** movies on Pi 5 under `/Media_Server/05` -> `Tamil Movies`, `English Movies`,
  `Dubbed Movies` (Indian Language Movie -> `/Media_Server/05/Indian Language Movies`, not yet confirmed);
  TV shows `/cloud/01`; anime `/cloud/02/Anime` (host 192.168.0.108 = Pi 4; Pi 5 is 192.168.0.106).
- Filing layout: Movies `Title (Year)/Title (Year).ext`; TV/anime `Show/Season NN/Show - SNNEENN.ext`.
- No seeding: torrents are stopped/removed (files kept) when finished, then moved from the node's download folder.
- Source-agnostic: no site-specific code. The owner only uses sources they are entitled to; do NOT write selectors
  for or add pirate/unlicensed sites (an example CC/public-domain source is seeded).
- Secrets editable in the Settings page are stored encrypted in the DB (key from APP_SECRET); `.env` only needs
  APP_SECRET, DATABASE_URL and the first AUTH_PASSWORD_HASH (single-quoted: Compose interpolates `$`).

## Commands
- Backend tests: `cd backend && python -m pytest -q`  (Python >= 3.12; node agent tests import `node_agent/`)
- Frontend: `cd frontend && npm run build`
- Deploy controller: `docker compose -f deploy/docker-compose.yml up -d --build` (UI is built into the image)
- Migrations are Alembic (`backend/alembic`), run automatically at startup. New NOT NULL columns need a server_default.

## Conventions
- Branch: develop on `ccr-e8c24b02-3aabtf`; no PR unless asked. One commit per logical change, tests green first.
- Keep resource use low (Pi 4/5): single worker, in-process scheduler, no heavy deps.
