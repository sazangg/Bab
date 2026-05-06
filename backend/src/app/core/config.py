from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BAB_", extra="ignore")

    database_url: str = Field(default="sqlite+aiosqlite:///./bab.db")
    secret_key: str = Field(default="dev-secret-key-change-me-minimum-32-chars")
    encryption_key: str | None = None
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
