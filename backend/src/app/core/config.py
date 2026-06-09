from functools import lru_cache
from typing import Any

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
    assets_dir: str = Field(
        default="./var/assets",
        validation_alias="BAB_ASSETS_DIR",
    )
    default_organization_name: str = Field(
        default="Default Organization",
        validation_alias="BAB_DEFAULT_ORGANIZATION_NAME",
    )
    default_team_name: str = Field(
        default="Default Team",
        validation_alias="BAB_DEFAULT_TEAM_NAME",
    )
    default_admin_email: str = Field(
        default="admin@example.com",
        validation_alias="BAB_DEFAULT_ADMIN_EMAIL",
    )
    default_admin_password: str = Field(
        default="admin-password-change-me",
        min_length=12,
        validation_alias="BAB_DEFAULT_ADMIN_PASSWORD",
    )
    refresh_cookie_secure: bool | None = Field(
        default=None,
        validation_alias="BAB_REFRESH_COOKIE_SECURE",
    )
    refresh_cookie_samesite: str = Field(
        default="lax",
        validation_alias="BAB_REFRESH_COOKIE_SAMESITE",
    )
    refresh_cookie_domain: str | None = Field(
        default=None,
        validation_alias="BAB_REFRESH_COOKIE_DOMAIN",
    )
    refresh_cookie_path: str = Field(
        default="/api/v1/auth",
        validation_alias="BAB_REFRESH_COOKIE_PATH",
    )
    run_live_openai_tests: bool = Field(
        default=False,
        validation_alias="BAB_RUN_LIVE_OPENAI_TESTS",
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    live_openai_model: str | None = Field(
        default=None,
        validation_alias="BAB_LIVE_OPENAI_MODEL",
    )
    usage_retention_days: int | None = Field(
        default=None,
        ge=1,
        validation_alias="BAB_USAGE_RETENTION_DAYS",
    )

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("BAB_ENVIRONMENT must be development, test, or production")
        return normalized

    @field_validator("refresh_cookie_samesite")
    @classmethod
    def validate_refresh_cookie_samesite(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("BAB_REFRESH_COOKIE_SAMESITE must be lax, strict, or none")
        return normalized

    @field_validator("usage_retention_days", mode="before")
    @classmethod
    def normalize_usage_retention_days(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

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


def validate_runtime_settings(current_settings: Settings | None = None) -> None:
    current_settings = current_settings or settings
    if current_settings.environment != "production":
        return

    errors: list[str] = []
    if current_settings.database_url.startswith("sqlite"):
        errors.append("DATABASE_URL must not use SQLite in production")
    if current_settings.default_admin_password == "admin-password-change-me":
        errors.append("BAB_DEFAULT_ADMIN_PASSWORD must be changed in production")
    if current_settings.secret_key == "change-me-to-at-least-32-characters":
        errors.append("BAB_SECRET_KEY must be changed in production")

    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
