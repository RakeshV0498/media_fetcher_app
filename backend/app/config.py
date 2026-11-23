from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_secret: str = "dev-insecure"
    database_url: str = "sqlite:///./data/app.db"
    downloads_enabled: bool = False  # safe default: downloads OFF
    home_public_ip: str = ""
    user_agent: str = "MediaFetcher/0.1"
    auth_username: str = "admin"
    auth_password_hash: str = ""
    session_hours: int = 24 * 7
    download_client: str = "mock"  # mock | qbittorrent
    vpn_ok_override: bool = False  # tests only
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    media_roots: str = ""  # comma-separated allowed final roots; empty = unrestricted
    tmdb_api_key: str = ""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    app_base_url: str = ""  # shown in Telegram messages, e.g. http://pi5.lan:8000
    scan_min_delay: float = 1.0
    scan_max_delay: float = 4.0


settings = Settings()
