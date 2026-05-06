from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./bab.db",
        validation_alias="DATABASE_URL",
    )
    secret_key: str = Field(min_length=32, validation_alias="BAB_SECRET_KEY")
    encryption_key: str = Field(validation_alias="BAB_ENCRYPTION_KEY")
    environment: str = Field(default="development", validation_alias="BAB_ENVIRONMENT")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
