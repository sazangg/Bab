from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = Field(default="Bab API", validation_alias="BAB_APP_NAME")
    app_version: str = Field(default="0.1.0", validation_alias="BAB_APP_VERSION")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./bab.db",
        validation_alias="DATABASE_URL",
    )
    secret_key: str = Field(min_length=32, validation_alias="BAB_SECRET_KEY")
    # Dedicated key for the tamper-evident audit-log HMAC. Kept separate from
    # secret_key so the JWT signing key can be rotated without invalidating the
    # historical audit chain. Falls back to secret_key when unset (legacy behavior).
    audit_signing_key: str | None = Field(
        default=None,
        validation_alias="BAB_AUDIT_SIGNING_KEY",
    )
    encryption_key: str = Field(validation_alias="BAB_ENCRYPTION_KEY")
    environment: str = Field(
        default="development",
        validation_alias="BAB_ENVIRONMENT",
    )
    proxy_max_body_bytes: int = Field(
        default=1_000_000,
        validation_alias="BAB_PROXY_MAX_BODY_BYTES",
    )
    # When false (default), provider base URLs that resolve to private/loopback/
    # link-local addresses are rejected (SSRF guard). Self-hosted single-tenant
    # deployments that target an internal model server can opt in.
    allow_private_provider_urls: bool = Field(
        default=False,
        validation_alias="BAB_ALLOW_PRIVATE_PROVIDER_URLS",
    )
    public_app_url: str | None = Field(default=None, validation_alias="BAB_PUBLIC_APP_URL")
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
    activity_retention_days: int | None = Field(
        default=None,
        ge=1,
        validation_alias="BAB_ACTIVITY_RETENTION_DAYS",
    )
    trace_retention_days: int = Field(
        default=30,
        ge=1,
        validation_alias="BAB_TRACE_RETENTION_DAYS",
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

    @field_validator(
        "usage_retention_days",
        "activity_retention_days",
        "trace_retention_days",
        mode="before",
    )
    @classmethod
    def normalize_retention_days(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("public_app_url")
    @classmethod
    def validate_public_app_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        parsed = urlparse(stripped)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("BAB_PUBLIC_APP_URL must be an app origin URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("BAB_PUBLIC_APP_URL must be an app origin URL")
        return stripped.rstrip("/")

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
