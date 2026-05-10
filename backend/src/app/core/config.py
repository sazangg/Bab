from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./bab.db",
        validation_alias="DATABASE_URL",
    )
    secret_key: str = Field(min_length=32, validation_alias="BAB_SECRET_KEY")
    encryption_key: str = Field(validation_alias="BAB_ENCRYPTION_KEY")
    environment: str = Field(
        default="development",
        validation_alias="BAB_ENVIRONMENT",
    )
    proxy_max_body_bytes: int = Field(
        default=1_000_000,
        validation_alias="BAB_PROXY_MAX_BODY_BYTES",
    )

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, value: str) -> str:
        try:
            Fernet(value.encode())
        except ValueError as exc:
            raise ValueError(
                "BAB_ENCRYPTION_KEY must be a Fernet key. Generate one with: "
                'uv run python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
