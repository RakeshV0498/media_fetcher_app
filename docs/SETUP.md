# Media Fetcher: setup guide and how it works

Self-hosted release monitor with approval-based downloads, filed into your Jellyfin libraries.
This guide covers a two-Pi setup: **Pi 5** (controller + movie node) and **Pi 4** (TV/anime node).
You are responsible for only fetching content you are entitled to.

## 1. How it works

**The pieces**

| Piece | Where | Port | What it does |
|---|---|---|---|
| Controller | Pi 5 | 8000 | The web app, database and scheduler. The only thing you open in a browser. |
| Node stack | each Pi | 8080 (qBittorrent), 8800 (agent) | qBittorrent downloads; the agent checks disk space and files finished downloads into the library. |
| VPN (gluetun) | optional, per node | | Only if you want it. Downloads work without a VPN. |
| Browser service | optional, Pi 5 | internal | Renders JavaScript-built pages for the source assistant and scans. |
| Telegram bot | optional | | New releases with Approve / Reject buttons. |

**Daily flow**

1. **Sources.** You add a website. The app looks for a feed first; if there is none, **Analyze page** works out the selectors
   for you and shows a preview of what a scan would read. Sites that list titles on one page and show the resolutions on a page per
   title use **Load versions**. Sites built with JavaScript can use the optional browser.
2. **Scans** run on a schedule. Entries are grouped into one release per title with all its versions (720p, 1080p, ...) attached.
   TMDB adds posters and suggests a library.
3. **Review.** You see the top 5 versions ranked by seeders, pick one and a library, then **Approve**. Nothing downloads without approval.
4. **Approve checks** that *Downloads enabled* is on, that the node has an agent, that there is enough disk space, and, only if
   you turned *Require VPN to download* on, that the VPN is up. It then adds the torrent to the qBittorrent of the node that the
   library belongs to, saving into that node's download folder.
5. **When it finishes** the torrent is stopped (no seeding) and the agent moves the file into your library:
   movies to `Title (Year)/Title (Year).ext`, TV and anime to `Show/Season NN/Show - SNNEENN.ext`. Jellyfin is then refreshed.
6. **Problems show on the Downloads page.** Unknown season: *needs attention* with a **Set season** button. A file that already
   exists: *duplicate* (never overwritten). A torrent qBittorrent does not list after 10 minutes: *failed* with the reason.
7. **Settings** holds what used to live in `.env`. Values saved there are stored in the database, override `.env`, and secrets are
   stored encrypted.

## 2. Prerequisites (each Pi)

- Git, Docker and Docker Compose. On a Pi without Docker:
  `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker pi`, then log out and back in.
- Your disks mounted: Pi 5 `/Media_Server/05`; Pi 4 `/cloud/01` and `/cloud/02`.
- Free space. The app refuses downloads when a disk is too full.

## 3. Get the code (each Pi)

```bash
git clone -b ccr-e8c24b02-3aabtf https://github.com/RakeshV0498/media_fetcher_app.git ~/Documents/mediaFetcher
cd ~/Documents/mediaFetcher        # already cloned? run: git pull
```

## 4. Controller (Pi 5 only)

```bash
cp .env.example .env && chmod 600 .env
openssl rand -hex 32               # put it in .env as APP_SECRET=
openssl rand -hex 24               # put it in .env as NODE_AGENT_TOKEN= (keep a copy: the Pi 4 needs the same value)
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml run --rm controller python -m app.hashpw
```

Paste the line the last command prints into `.env` (keep its single quotes, because Docker Compose treats `$` specially), then:

```bash
docker compose -f deploy/docker-compose.yml up -d --force-recreate
```

Open `http://192.168.0.106:8000` and sign in as `admin` with the password you hashed.
After any `.env` change run the `--force-recreate` command again.

## 5. Download node on each Pi (no VPN)

```bash
cp deploy/node.env.example deploy/node.env && chmod 600 deploy/node.env
nano deploy/node.env
```

Delete the gluetun/VPN lines, then set:

| | Pi 5 | Pi 4 |
|---|---|---|
| `DOWNLOADS_DIR` | `/Media_Server/05/_downloads` | `/cloud/02/_downloads` |
| `MEDIA_ROOTS` | `/Media_Server/05` | `/cloud/01,/cloud/02` |
| `NODE_AGENT_TOKEN` | the same value on both Pis and in the controller's `.env` | |
| `TZ`, `PUID`, `PGID` | `Asia/Kolkata`, `1000`, `1000` | |

Create the download folder (`mkdir -p <DOWNLOADS_DIR>`), then create `deploy/docker-compose.local.yml` so the agent can see your
library disks (same path inside and outside the container). This file is git-ignored, so `git pull` never conflicts with it:

```yaml
services:
  agent:
    volumes:
      - /Media_Server/05:/Media_Server/05      # Pi 4: list /cloud/01:/cloud/01 and /cloud/02:/cloud/02
```

Start the node stack and check it:

```bash
docker compose -f deploy/docker-compose.node.novpn.yml -f deploy/docker-compose.local.yml --env-file deploy/node.env up -d --build
T=$(grep ^NODE_AGENT_TOKEN= deploy/node.env | cut -d= -f2-)
curl -s -H "Authorization: Bearer $T" localhost:8800/info        # lists your download and media folders
```

Keep the download folder on the same disk as the library where you can: moves are then instant. On the Pi 4, downloads go to
`/cloud/02`, so anime filing is instant and TV filing into `/cloud/01` is a verified copy.

## 6. qBittorrent password (each Pi)

```bash
docker logs deploy-qbittorrent-1 2>&1 | grep -i password
```

Log in as `admin` at `http://<pi-ip>:8080` with that temporary password, then set a permanent one under
Tools, Options, Web UI. **Use the same username and password on both Pis**: the controller uses one shared qBittorrent login.

## 7. Settings page (in the web UI)

| Tab | What to do |
|---|---|
| **Integrations** | TMDB API key, Jellyfin URL and API key. Press **Test TMDB** and **Test Jellyfin**. |
| **Downloads** | Set *Download client* to `qbittorrent`, turn on **Downloads enabled**, enter the qBittorrent username and password and the node agent token. |
| **Nodes & VPN** | Agent and qBittorrent URLs for each node (`http://192.168.0.106:8800` and `:8080`; the same on `192.168.0.108`). Press **Test connection**: every line should pass. |
| **Libraries** | Check each tag's node and folder: Tamil, English and Dubbed Movies under `/Media_Server/05`, TV at `/cloud/01`, Anime at `/cloud/02/Anime`. Use **Browse** to pick or create folders. |
| **Telegram** | Optional. See section 9. |
| **General**, **Security** | Preferred quality, scanner User-Agent, admin username and password. |

## 8. First test

The app seeds one openly licensed source on first start (WebTorrent's Creative Commons / public-domain test films). In **Review**,
approve one (for example Sintel), pick a library, and watch **Downloads** go Downloading, Filing, Filed. Then check that the folder
exists on the Pi 5, for example `ls "/Media_Server/05/English Movies"`.

## 9. Optional extras

- **Telegram.** Create a bot with @BotFather and press Start in its chat. Enter the token and your chat ID in Settings, Telegram, and
  press **Send test message**. Only that chat can approve or reject.
- **VPN.** Use `deploy/docker-compose.node.yml` instead of the no-VPN file, fill in your provider's settings in `deploy/node.env`,
  then turn on **Require VPN to download** in Settings, Downloads. Verify the IP and kill switch with the README checklist first.
- **Browser for JavaScript sites.** Add `BROWSER_TOKEN=<any long random string>` to the controller's `.env`, then run
  `docker compose -f deploy/docker-compose.yml --profile browser up -d --build`. In Settings, Integrations, turn on
  **Render JavaScript pages with a browser** and press **Test browser**. In the Sources assistant, **Try with the browser** appears
  when a plain fetch finds nothing on a script-driven page. It never tries to get past CAPTCHAs, Cloudflare checks or logins:
  such pages are reported as blocked, so use **Paste page HTML** for them.

## 10. Updating

```bash
cd ~/Documents/mediaFetcher && git pull
docker compose -f deploy/docker-compose.yml up -d --build          # Pi 5 controller
```

Re-run the node `up -d --build` command only if node files changed. The database upgrades itself. Docker may print an
"orphan containers" warning because the controller and node stack share a project name; it is harmless. Do not add `--remove-orphans`.

## 11. Troubleshooting

| Symptom | What to do |
|---|---|
| App will not load | `docker logs deploy-controller-1 --tail 50`; the last lines say why. |
| A *Test connection* line fails | The line says why: wrong qBittorrent login, agent token mismatch, or unreachable. |
| "Downloading" never moves | After 10 minutes it becomes *failed* with a reason. A 404 means the link was removed at the source. |
| Approve refused: disk space | The target disk is too full. Free some space, or lower *Keep free disk space* in Settings, Downloads. |
| Approve refused: no node agent | The node's agent URL is not set or the agent is not running. |
| Login fails after editing `.env` | Keep the single quotes around `AUTH_PASSWORD_HASH`, then `--force-recreate`. |
| Source scan error "No feed was found" | Press **Add selectors** on the source, then **Analyze page**. |
