"""Admin-editable settings: DB overrides layered over .env defaults.

* Values live in the `app_settings` table; secrets are Fernet-encrypted with a key derived from APP_SECRET.
* `apply_overrides` copies them onto the `settings` singleton, so code that reads `settings.x` at call
  time picks changes up immediately.  Clearing a key restores the .env default.
* Bootstrap values (APP_SECRET, DATABASE_URL) are deliberately NOT editable here.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting


class SettingError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str  # tab id
    kind: str = "text"  # text | url | secret | bool | int | float | select
    help: str = ""
    options: tuple[str, ...] = ()
    danger: bool = False
    min: float | None = None
    max: float | None = None


FIELDS: tuple[Field, ...] = (
    # General
    Field("user_agent", "Scanner User-Agent", "general", help="Sent to the sites you scan (per-source value overrides it)."),
    Field("scan_min_delay", "Min delay between scans (s)", "general", "float", min=0, max=600),
    Field("scan_max_delay", "Max delay between scans (s)", "general", "float", min=0, max=600),
    # Integrations
    Field("tmdb_api_key", "TMDB API key", "integrations", "secret", "Posters, overviews and anime season mapping."),
    Field("jellyfin_url", "Jellyfin URL", "integrations", "url", "e.g. http://192.168.0.10:8096"),
    Field("jellyfin_api_key", "Jellyfin API key", "integrations", "secret", "Dashboard → Advanced → API Keys."),
    Field("browser_enabled", "Render JavaScript pages with a browser", "integrations", "bool",
          help="Optional. Lets sources that build their list with JavaScript be analyzed and scanned. Needs the browser "
               "service (docker compose --profile browser)."),
    Field("browser_url", "Browser service URL", "integrations", "url", "Default http://browser:8100 (inside Docker)."),
    Field("browser_token", "Browser service token", "integrations", "secret",
          "Must equal BROWSER_TOKEN in the controller's .env (the service reads it from there)."),
    Field("browser_timeout_s", "Browser page timeout (s)", "integrations", "int", min=5, max=120),
    # Telegram
    Field("telegram_enabled", "Enable Telegram bot", "telegram", "bool"),
    Field("telegram_bot_token", "Bot token", "telegram", "secret", "From @BotFather."),
    Field("telegram_chat_id", "Your chat ID", "telegram", help="Only this chat can approve or reject."),
    Field("app_base_url", "App URL shown in messages", "telegram", "url", "e.g. http://pi5.lan:8000"),
    # Downloads
    Field("downloads_enabled", "Downloads enabled", "downloads", "bool", danger=True,
          help="Master switch. Real downloads also need the VPN check to pass on the target node."),
    Field("require_vpn", "Require VPN to download", "downloads", "bool",
          help="Off: downloads work without a VPN. On: a download is refused unless the target node's VPN check passes."),
    Field("download_client", "Download client", "downloads", "select", options=("mock", "qbittorrent"),
          help="'mock' simulates downloads without touching the network."),
    Field("qbit_username", "qBittorrent username", "downloads"),
    Field("qbit_password", "qBittorrent password", "downloads", "secret"),
    Field("node_agent_token", "Node agent token", "downloads", "secret", "Shared secret; must match NODE_AGENT_TOKEN on each Pi."),
    Field("home_public_ip", "Home public IP (optional)", "downloads", help="Normally measured by the node agent. Set only to override."),
    Field("min_free_reserve_gb", "Keep free disk space (GB)", "downloads", "int", min=0, max=10000),
    Field("media_roots", "Controller-local media roots", "downloads",
          help="Comma-separated. Only used when a node has no agent (single-host setups)."),
    # Security
    Field("auth_username", "Admin username", "security"),
)
BY_KEY = {f.key: f for f in FIELDS}
ENV_DEFAULTS = {f.key: getattr(settings, f.key) for f in FIELDS}
SECRET_KEYS = {f.key for f in FIELDS if f.kind == "secret"} | {"auth_password_hash"}


# ---------- crypto ----------
def _fernet() -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"media-fetcher-settings", info=b"v1").derive(
        settings.app_secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # APP_SECRET changed: treat as unset


# ---------- raw key/value (also used for per-node VPN settings) ----------
def put(db: Session, key: str, value: str, secret: bool = False) -> None:
    row = db.get(AppSetting, key) or AppSetting(key=key)
    row.value, row.is_secret = (encrypt(value) if secret else value), secret
    db.add(row)


def get(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    if row is None:
        return None
    return decrypt(row.value) if row.is_secret else row.value


def delete(db: Session, key: str) -> None:
    row = db.get(AppSetting, key)
    if row is not None:
        db.delete(row)


def is_set(db: Session, key: str) -> bool:
    return get(db, key) not in (None, "")


# ---------- typed settings ----------
def coerce(f: Field, raw: object) -> object:
    try:
        if f.kind == "bool":
            if isinstance(raw, bool):
                return raw
            if str(raw).lower() in ("true", "1", "yes", "on"):
                return True
            if str(raw).lower() in ("false", "0", "no", "off"):
                return False
            raise ValueError
        if f.kind in ("int", "float"):
            v = int(raw) if f.kind == "int" else float(raw)  # type: ignore[arg-type]
            if (f.min is not None and v < f.min) or (f.max is not None and v > f.max):
                raise SettingError(f"{f.label}: must be between {f.min:g} and {f.max:g}")
            return v
    except (TypeError, ValueError) as e:
        if isinstance(e, SettingError):
            raise
        raise SettingError(f"{f.label}: invalid {f.kind} value") from e
    text = str(raw).strip()
    if f.kind == "select" and text not in f.options:
        raise SettingError(f"{f.label}: must be one of {', '.join(f.options)}")
    if f.kind == "url" and text and not text.startswith(("http://", "https://")):
        raise SettingError(f"{f.label}: must start with http:// or https://")
    return text


def apply_overrides(db: Session) -> list[str]:
    """Load DB values onto `settings`. Returns keys whose effective value changed."""
    changed: list[str] = []
    rows = {r.key: r for r in db.query(AppSetting).all()}
    for f in FIELDS:
        row = rows.get(f.key)
        value: object = ENV_DEFAULTS[f.key]
        if row is not None:
            raw = decrypt(row.value) if row.is_secret else row.value
            if raw is not None:
                value = coerce(f, raw) if raw != "" or f.kind in ("text", "url", "secret") else value
        if getattr(settings, f.key) != value:
            setattr(settings, f.key, value)
            changed.append(f.key)
    row = rows.get("auth_password_hash")
    pw = (decrypt(row.value) if row.is_secret else row.value) if row else None
    if pw and settings.auth_password_hash != pw:
        settings.auth_password_hash = pw
        changed.append("auth_password_hash")
    return changed


@dataclass
class Update:
    values: dict[str, object] = field(default_factory=dict)
    clear: list[str] = field(default_factory=list)


def save(db: Session, upd: Update) -> list[str]:
    """Validate + persist. Secret fields: empty string means 'leave unchanged'. Returns changed keys."""
    for key in list(upd.values) + upd.clear:
        if key not in BY_KEY:
            raise SettingError(f"unknown setting: {key}")
    staged: list[tuple[Field, object]] = []
    for key, raw in upd.values.items():
        f = BY_KEY[key]
        if f.kind == "secret" and (raw is None or raw == ""):
            continue
        staged.append((f, coerce(f, raw)))
    for f, v in staged:
        put(db, f.key, str(v), secret=f.kind == "secret")
    for key in upd.clear:
        delete(db, key)
    db.commit()
    return apply_overrides(db)


def describe(db: Session) -> list[dict]:
    rows = {r.key: r for r in db.query(AppSetting).all()}
    out = []
    for f in FIELDS:
        row = rows.get(f.key)
        d = {"key": f.key, "label": f.label, "group": f.group, "kind": f.kind, "help": f.help,
             "options": list(f.options), "danger": f.danger,
             "source": "db" if row is not None else "env"}
        if f.kind == "secret":
            readable = row is not None and decrypt(row.value) not in (None, "")
            d["set"] = readable or bool(ENV_DEFAULTS[f.key])
            d["unreadable"] = row is not None and decrypt(row.value) is None
        else:
            d["value"] = getattr(settings, f.key)
        out.append(d)
    return out
