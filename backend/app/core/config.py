from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MAWA_")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://mawa:mawa@localhost:5432/mawapress"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-only-change-me"
    jwt_access_minutes: int = 15
    site_url: str = "https://mawapress.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
