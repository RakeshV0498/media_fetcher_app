from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_secret: str = "dev-insecure"
    database_url: str = "sqlite:///./data/app.db"
    downloads_enabled: bool = False  # safe default: downloads OFF
    home_public_ip: str = ""
    user_agent: str = "MediaFetcher/0.1"
    scan_min_delay: float = 1.0
    scan_max_delay: float = 4.0


settings = Settings()
