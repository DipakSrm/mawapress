import logging
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-change-me-this-is-not-a-real-secret"
MIN_JWT_SECRET_LENGTH = 32

log = logging.getLogger("mawa.config")


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
    trust_proxy: bool = False  # honour client_ip_header / X-Forwarded-For (only behind a proxy that sets them)
    client_ip_header: str = "CF-Connecting-IP"  # preferred client-IP header when trust_proxy is on
    rate_limit_window_seconds: int = 60
    stats_salt: str | None = None  # secret for the daily view-dedup salt; falls back to jwt_secret
    # Outbox worker integrations; each is skipped (event still marked processed) while unset.
    revalidate_url: str | None = None
    revalidate_secret: str | None = None
    cf_zone_id: str | None = None
    cf_api_token: str | None = None
    # Media storage: "local" (dev/tests; served by FastAPI at /media) or "s3" (Cloudflare R2).
    storage: str = "local"
    media_local_dir: str = ".media"
    media_base_url: str = ""  # public origin of the s3 bucket/CDN; empty = same-origin relative URLs
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    @model_validator(mode="after")
    def _require_safe_settings_outside_dev(self) -> "Settings":
        if self.env != "dev" and (
            self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH
        ):
            raise ValueError(
                f"MAWA_JWT_SECRET must be set to at least {MIN_JWT_SECRET_LENGTH} random characters when env is not 'dev'"
            )
        if self.storage not in ("local", "s3"):
            raise ValueError("MAWA_STORAGE must be 'local' or 's3'")
        if self.storage == "s3":
            required = ("s3_endpoint", "s3_bucket", "s3_access_key", "s3_secret_key", "media_base_url")
            missing = [f"MAWA_{n.upper()}" for n in required if not getattr(self, n)]
            if missing:
                raise ValueError(f"MAWA_STORAGE=s3 requires {', '.join(missing)}")
        if self.env != "dev" and not self.cookie_secure:
            raise ValueError("MAWA_COOKIE_SECURE must be true when env is not 'dev'")
        return self


    def startup_warnings(self) -> list[str]:
        warnings = []
        if self.env != "dev" and not self.trust_proxy:
            warnings.append(
                "MAWA_TRUST_PROXY is false: every client shares the proxy's IP for rate limiting and view dedup. "
                "Set it to true when running behind Nginx/Cloudflare."
            )
        if self.env != "dev" and self.storage == "local":
            warnings.append(
                "MAWA_STORAGE=local: uploads live on this machine's disk and are served by the API. "
                "Use MAWA_STORAGE=s3 in production."
            )
        return warnings


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for message in settings.startup_warnings():
        log.warning(message)
    return settings
