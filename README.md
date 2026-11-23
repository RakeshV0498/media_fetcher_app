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

## Enrichment & Telegram
- Set `TMDB_API_KEY` for posters, overviews, better tag suggestions and automatic anime
  absolute-episode -> season/episode mapping (e.g. One Piece 1056). AniList needs no key.
  Without a key everything still works; unresolved anime fall back to *Set season…*.
- Telegram is off unless `TELEGRAM_ENABLED=true` with `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_CHAT_ID`. New releases arrive with one button per top-ranked variant plus Reject.
  Only your chat id is obeyed, and Approve uses the same download gate as the web UI
  (it needs a suggested tag; otherwise pick it in the web UI).

## Download nodes (VPN + qBittorrent) — one stack per Pi
Topology: **one controller** (Pi 5: UI, DB, scheduler, approvals) + **one node stack per Pi**
(`deploy/docker-compose.node.yml`: `gluetun` + `qbittorrent` + a thin `agent`). The Pi 5 runs a node stack too.
The controller talks to each node's qBittorrent WebUI and agent over the LAN.

1. On each Pi: `cp deploy/node.env.example deploy/node.env`, fill in your VPN provider's gluetun
   variables (see the gluetun wiki), `NODE_AGENT_TOKEN`, `DOWNLOADS_DIR`, `MEDIA_ROOTS`. Add one volume line per
   media disk in the compose file (same path inside and outside the container).
   `docker compose -f deploy/docker-compose.node.yml --env-file deploy/node.env up -d`
2. Open qBittorrent's WebUI (`http://<pi>:8080`), set a password; put it in the controller `.env`
   (`QBIT_USERNAME`/`QBIT_PASSWORD`) with the same `NODE_AGENT_TOKEN`, set `DOWNLOAD_CLIENT=qbittorrent`,
   and enter the agent/qBittorrent URLs on the **Nodes** page (or `NODE_PI*_URL` in `.env`). Set each tag's final folder.
3. **Do not set `DOWNLOADS_ENABLED=true` until this checklist passes on every node:**
   - [ ] Nodes page shows *VPN protected* and the VPN IP differs from the Home IP (compare with an
         "what is my ip" site run from your PC).
   - [ ] `docker exec <qbittorrent container> wget -qO- https://api.ipify.org` prints the **VPN** IP, not your home IP.
   - [ ] Kill switch: `docker compose -f deploy/docker-compose.node.yml stop gluetun` (or `docker network disconnect`),
         then the same `wget` **fails/times out** and the Nodes page flips to *VPN not verified*.
         Start gluetun again; it must recover.
   - [ ] With a *legal* torrent (e.g. a Linux ISO) approved on a node: it downloads, stops after completion
         (no seeding), and is moved to the tag's folder; Jellyfin refreshes.
   - [ ] An approval while the VPN is down is refused with a 409 and nothing appears in qBittorrent.
4. Then set `DOWNLOADS_ENABLED=true` and restart the controller.

Safety behaviour: approvals are refused unless the flag is on, the node's tunnel is up, its public IP is known and
differs from the home IP (measured by the agent outside the VPN, or `HOME_PUBLIC_IP`), and the target disk has room
(size x1.1 + `MIN_FREE_RESERVE_GB`). Any error in these checks blocks the download. The agent only reads/writes
under `DOWNLOAD_ROOTS` / `MEDIA_ROOTS`.

## Login password
Run `docker compose -f deploy/docker-compose.yml run --rm controller python -m app.hashpw` and paste the printed
line (`AUTH_PASSWORD_HASH='$argon2id$...'`) into `.env`. **Keep the single quotes** - Docker Compose otherwise
interpolates the `$` characters and mangles the hash. After any `.env` change run
`docker compose -f deploy/docker-compose.yml up -d --force-recreate`.

## Settings page (admin)
After signing in, **Settings** holds everything you would otherwise put in `.env`, grouped in tabs:
General · Integrations (TMDB, Jellyfin) · Telegram · Downloads · Libraries (tag → node → folder, with a folder browser)
· Nodes & VPN · Security (username, change password). Changes apply immediately, no restart.

- Values saved in the UI live in the database and **override `.env`**; "reset" on a field restores the `.env` value.
  Secrets are encrypted with a key derived from `APP_SECRET`, are never sent back to the browser (shown as
  "saved"), and become unreadable if `APP_SECRET` changes (re-enter them). `.env` still needs `APP_SECRET`,
  `DATABASE_URL` and the first `AUTH_PASSWORD_HASH`.
- Folder browsing happens on the node itself and is limited to that Pi's `MEDIA_ROOTS` (set in its `node.env`;
  deliberately not editable remotely, it is the security boundary). You can create new sub-folders there.
- **VPN provider settings** (per node) are pushed by the node agent to gluetun's settings API, so no SSH or restart.
  One-time setup per Pi: generate a key (`openssl rand -base64 24`), put it in `deploy/gluetun-auth.toml`
  (`apikey = ...`) and as `GLUETUN_API_KEY` in `node.env`. Gluetun still needs a valid first-time VPN config in
  `node.env` to start at all; afterwards you can change it from the UI. This path needs a recent gluetun and has
  **not been tested against a real gluetun yet** - use *Save & apply* on one node and confirm the Nodes tab shows
  "VPN protected" before relying on it.
