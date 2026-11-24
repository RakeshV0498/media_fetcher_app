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

## Download nodes (qBittorrent, VPN optional) — one stack per Pi
**A VPN is optional.** Without one, use `deploy/docker-compose.node.novpn.yml` (qBittorrent + agent, no gluetun) and leave
*Settings → Downloads → Require VPN to download* **off** (the default); your home IP is then visible to peers. Later you can
switch to the gluetun stack below and turn *Require VPN* on to refuse any download unless the VPN check passes.

Put per-Pi disk mounts in a git-ignored `deploy/docker-compose.local.yml` (added with a second `-f`) so `git pull` never conflicts.

Quick path without VPN, on each Pi: `cp deploy/node.env.example deploy/node.env`, set `NODE_AGENT_TOKEN`, `DOWNLOADS_DIR` and
`MEDIA_ROOTS` (Pi 5: `/Media_Server/05`; Pi 4: `/cloud/01,/cloud/02`), add the matching volume lines, then
`docker compose -f deploy/docker-compose.node.novpn.yml --env-file deploy/node.env up -d --build`. Set the qBittorrent
password in its WebUI, then fill in the agent / qBittorrent URLs and credentials in **Settings** and turn on *Downloads enabled*.

### With a VPN (gluetun)
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
3. **If you use a VPN, do not turn on *Require VPN* / downloads until this checklist passes on every node:**
   - [ ] Nodes page shows *VPN protected* and the VPN IP differs from the Home IP (compare with an
         "what is my ip" site run from your PC).
   - [ ] `docker exec <qbittorrent container> wget -qO- https://api.ipify.org` prints the **VPN** IP, not your home IP.
   - [ ] Kill switch: `docker compose -f deploy/docker-compose.node.yml stop gluetun` (or `docker network disconnect`),
         then the same `wget` **fails/times out** and the Nodes page flips to *VPN not verified*.
         Start gluetun again; it must recover.
   - [ ] With a *legal* torrent (e.g. a Linux ISO) approved on a node: it downloads, stops after completion
         (no seeding), and is moved to the tag's folder; Jellyfin refreshes.
   - [ ] An approval while the VPN is down is refused with a 409 and nothing appears in qBittorrent.
4. Then turn on *Require VPN to download* and *Downloads enabled* in Settings.

Safety behaviour: approvals are refused unless *Downloads enabled* is on and, when *Require VPN* is on, the node's tunnel is up, its public IP is known and
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

## Example source
On first start the app adds one openly licensed source, **WebTorrent free torrents** (Big Buck Bunny, Sintel,
Tears of Steel, Cosmos Laundromat: public domain / Creative Commons Blender films), so you can try the whole
flow (scan -> review -> approve -> download -> file) with content that is legal to download. Delete it any time;
it is not re-added. When a site has no feed and no selectors, the Sources page says so and offers **Add selectors**;
selectors also accept an optional `title_regex` to trim extra text from titles.

## Where do downloads go?
qBittorrent saves into the node's **download folder** (`DOWNLOADS_DIR` in `node.env`, or *Settings -> Nodes & VPN ->
Download folder*), in a sub-folder named after the tag's category. When a download finishes, the node agent moves the
video into the tag's **library folder** (`Title (Year)/...` or `Show/Season NN/...`) and the **Downloads** page lists the
final path. Keep the download folder on the same disk as the library so the move is an instant rename. Both folders must be
mounted at the same path inside the qBittorrent and agent containers (see `docker-compose.node.yml`).

## Sites with a listing page + a detail page per title
Some sites list titles on one page and show the resolutions only on each title's own page. Configure the source with
the listing selectors plus a `detail` block (same keys, applied to the detail page); the listing's `link` must point at
the detail page:

```json
{ "item": "div.entry", "title": "a.title", "link": "a.title@href",
  "detail": { "item": "div.version", "title": ".name", "magnet": "a.magnet@href", "size": ".size", "seeders": ".seeds" } }
```
A scan only reads the listing and creates the entries. When you want one, press **Load versions** on its card: only that
one detail page is fetched, and the resolutions then appear (ranked by seeders) to pick from. Detail pages are only fetched
from the source's own host.

## Auto-detect selectors (sites without a feed)
In **Sources → Add source**, enter the site's listing URL and press **Analyze page**. The assistant finds the repeating list
of entries and works out the selectors for title, link, magnet / `.torrent`, size and seeders (table headers like `SE`/`LE`,
class names, size patterns), then **previews what a scan would extract** so you can check it before using it.
- If the entries carry no download links (each title has its own page), it says so and offers **Step 2**: give any one
  entry's page and it detects the resolution blocks and fills in the `detail` part.
- Sites that block scrapers, need a login or build the list with JavaScript: use **Paste page HTML** (copy the page source
  with Ctrl+U in your browser).
- It cannot separate versions that are not wrapped in similar blocks, and it cannot read JavaScript-only pages. The proposal
  is always shown as JSON you can edit before saving.

## Optional: browser rendering for JavaScript sites
Some sites build their list with JavaScript, so a plain fetch (and the assistant) sees an empty page. An optional **browser
service** (Playwright + Chromium, in its own container) renders such pages. It is **off by default**.

1. In the controller `.env` set `BROWSER_TOKEN=<any long random string>` (shared by the controller and the service).
2. Start it: `docker compose -f deploy/docker-compose.yml --profile browser up -d --build` (first build downloads ~400 MB).
3. Settings -> Integrations: turn on **Render JavaScript pages with a browser** and press **Test browser**.
4. In **Sources**, either tick *Render with a browser* in the assistant (it offers **Try with the browser** automatically when a
   plain fetch finds nothing on a script-driven page), or set a source's **Fetch pages with = Browser**. Scans and *Load versions*
   for that source then use the browser. Optional *Wait for element* = a selector that appears once the list has loaded.

Limits and safety: one page at a time and a 768 MB memory cap (a Pi 5 with 4 GB is fine); images/fonts are not loaded; the service
refuses addresses on your own network (loopback/private/link-local) and `file:` URLs; it uses an honest browser and does **not**
try to get past CAPTCHAs, Cloudflare checks or logins - such pages are reported as blocked, use **Paste page HTML** for them.

**First start on a Pi (checklist, the arm64 image cannot be built where this was developed):**
`docker compose -f deploy/docker-compose.yml --profile browser up -d --build browser` -> `docker logs deploy-browser-1` shows
uvicorn running -> Settings -> *Test browser* says "Browser works (Chromium ...)" -> analyze a JavaScript page ->
watch `docker stats deploy-browser-1` stays under the cap. If Debian's Chromium misbehaves, edit `deploy/Dockerfile.browser`: replace
the apt line with `RUN playwright install --with-deps chromium` and remove `CHROMIUM_PATH`.
