from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-change-me-this-is-not-a-real-secret"
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MAWA_")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://mawa:mawa@localhost:5432/mawapress"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_access_minutes: int = 15
    site_url: str = "https://mawapress.com"
    refresh_days: int = 14
    cookie_secure: bool = True  # set MAWA_COOKIE_SECURE=false for plain-http local dev
    trust_proxy: bool = False  # honour X-Forwarded-For (only behind a proxy that sets it)
    rate_limit_window_seconds: int = 60
    # Outbox worker integrations; each is skipped (event still marked processed) while unset.
    revalidate_url: str | None = None
    revalidate_secret: str | None = None
    cf_zone_id: str | None = None
    cf_api_token: str | None = None

    @model_validator(mode="after")
    def _require_safe_settings_outside_dev(self) -> "Settings":
        if self.env != "dev" and (
            self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH
        ):
            raise ValueError(
                f"MAWA_JWT_SECRET must be set to at least {MIN_JWT_SECRET_LENGTH} random characters when env is not 'dev'"
            )
        if self.env != "dev" and not self.cookie_secure:
            raise ValueError("MAWA_COOKIE_SECURE must be true when env is not 'dev'")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
