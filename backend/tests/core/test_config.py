import pytest

from app.core.config import (
    Settings,
    validate_bootstrap_settings,
    validate_runtime_settings,
)


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://user:pass@db/bab",
        "secret_key": "changed-secret-key-with-more-than-32-chars",
        "encryption_key": "different-fernet-key",
        "default_admin_password": "admin-password-change-me",
        "metrics_enabled": False,
        "public_app_url": "https://app.example.com",
        "refresh_cookie_samesite": "lax",
        "refresh_cookie_secure": None,
        "rate_limit_enabled": False,
        "redis_url": None,
        "provider_runtime_state_backend": "memory",
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def test_production_rejects_sqlite_database() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="sqlite+aiosqlite:///./bab.db",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
        default_admin_password="changed-admin-password",
    )

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_runtime_settings(settings)


def test_development_allows_sqlite_database() -> None:
    settings = Settings.model_construct(
        environment="development",
        database_url="sqlite+aiosqlite:///./bab.db",
        secret_key="change-me-to-at-least-32-characters",
        encryption_key="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
        default_admin_password="admin-password-change-me",
    )

    validate_runtime_settings(settings)


def test_production_requires_redis_when_rate_limiting_enabled() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        rate_limit_enabled=True,
        redis_url=None,
    )

    with pytest.raises(RuntimeError, match="BAB_REDIS_URL"):
        validate_runtime_settings(settings)


def test_production_allows_missing_redis_when_rate_limiting_disabled() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        rate_limit_enabled=False,
        redis_url=None,
        metrics_enabled=False,
        public_app_url="https://app.example.com",
    )

    validate_runtime_settings(settings)


@pytest.mark.parametrize(
    "redis_url",
    [
        "redis://localhost:6379/0",
        "rediss://cache.example.com/0",
        "unix:///var/run/redis.sock",
    ],
)
def test_valid_redis_url_schemes_are_accepted(redis_url: str) -> None:
    settings = Settings(
        BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
        BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
        BAB_REDIS_URL=redis_url,
    )

    assert settings.redis_url == redis_url


@pytest.mark.parametrize(
    "redis_url",
    ["http://localhost:6379", "redis://", "redis://localhost:not-a-port"],
)
def test_invalid_redis_urls_are_rejected(redis_url: str) -> None:
    with pytest.raises(ValueError, match="BAB_REDIS_URL"):
        Settings(
            BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
            BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
            BAB_REDIS_URL=redis_url,
        )


def test_provider_runtime_state_backend_defaults_to_memory() -> None:
    settings = Settings(
        BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
        BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
    )

    assert settings.provider_runtime_state_backend == "memory"
    assert settings.metrics_enabled is True
    assert settings.metrics_bearer_token is None


def test_blank_metrics_bearer_token_is_normalized() -> None:
    settings = Settings(
        BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
        BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
        BAB_METRICS_BEARER_TOKEN="  ",
    )

    assert settings.metrics_bearer_token is None


def test_provider_runtime_redis_requires_redis_url() -> None:
    settings = Settings(
        BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
        BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
        BAB_PROVIDER_RUNTIME_STATE_BACKEND="redis",
    )

    with pytest.raises(RuntimeError, match="BAB_REDIS_URL"):
        validate_runtime_settings(settings)


def test_invalid_provider_runtime_state_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="BAB_PROVIDER_RUNTIME_STATE_BACKEND"):
        Settings(
            BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
            BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
            BAB_PROVIDER_RUNTIME_STATE_BACKEND="database",
        )


def test_production_requires_metrics_token_when_metrics_enabled() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        metrics_enabled=True,
        metrics_bearer_token=None,
        rate_limit_enabled=False,
        redis_url=None,
        provider_runtime_state_backend="memory",
        public_app_url="https://app.example.com",
    )

    with pytest.raises(RuntimeError, match="BAB_METRICS_BEARER_TOKEN"):
        validate_runtime_settings(settings)


def test_production_allows_disabled_metrics_without_token() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        metrics_enabled=False,
        metrics_bearer_token=None,
        rate_limit_enabled=False,
        redis_url=None,
        provider_runtime_state_backend="memory",
        public_app_url="https://app.example.com",
    )

    validate_runtime_settings(settings)


def test_production_allows_enabled_metrics_with_token() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        metrics_enabled=True,
        metrics_bearer_token="test-token",
        rate_limit_enabled=False,
        redis_url=None,
        provider_runtime_state_backend="memory",
        public_app_url="https://app.example.com",
    )

    validate_runtime_settings(settings)


def test_production_requires_public_app_url() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        metrics_enabled=False,
        public_app_url=None,
        refresh_cookie_samesite="lax",
        refresh_cookie_secure=None,
    )

    with pytest.raises(RuntimeError, match="BAB_PUBLIC_APP_URL"):
        validate_runtime_settings(settings)


def test_production_accepts_public_app_url() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        metrics_enabled=False,
        public_app_url="https://app.example.com",
        refresh_cookie_samesite="lax",
        refresh_cookie_secure=None,
    )

    validate_runtime_settings(settings)


@pytest.mark.parametrize("refresh_cookie_secure", [None, True])
def test_production_accepts_secure_samesite_none_cookie(
    refresh_cookie_secure: bool | None,
) -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        metrics_enabled=False,
        public_app_url="https://app.example.com",
        refresh_cookie_samesite="none",
        refresh_cookie_secure=refresh_cookie_secure,
    )

    validate_runtime_settings(settings)


def test_production_rejects_insecure_samesite_none_cookie() -> None:
    settings = Settings.model_construct(
        environment="production",
        database_url="postgresql+asyncpg://user:pass@db/bab",
        secret_key="changed-secret-key-with-more-than-32-chars",
        encryption_key="different-fernet-key",
        default_admin_password="changed-admin-password",
        metrics_enabled=False,
        public_app_url="https://app.example.com",
        refresh_cookie_samesite="none",
        refresh_cookie_secure=False,
    )

    with pytest.raises(RuntimeError, match="BAB_REFRESH_COOKIE_SECURE"):
        validate_runtime_settings(settings)


def test_runtime_rejects_default_admin_password_in_production() -> None:
    with pytest.raises(RuntimeError, match="BAB_DEFAULT_ADMIN_PASSWORD"):
        validate_runtime_settings(_production_settings())


def test_bootstrap_accepts_unused_default_admin_password_in_production() -> None:
    validate_bootstrap_settings(_production_settings())


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"database_url": "sqlite+aiosqlite:///./bab.db"}, "DATABASE_URL"),
        (
            {"encryption_key": "mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw="},
            "BAB_ENCRYPTION_KEY",
        ),
        ({"public_app_url": None}, "BAB_PUBLIC_APP_URL"),
        ({"rate_limit_enabled": True}, "BAB_REDIS_URL"),
    ],
)
def test_bootstrap_keeps_shared_production_safety_checks(
    overrides: dict[str, object],
    expected_error: str,
) -> None:
    with pytest.raises(RuntimeError, match=expected_error):
        validate_bootstrap_settings(_production_settings(**overrides))


def test_usage_retention_defaults_to_no_deletion_intent() -> None:
    settings = Settings.model_construct(
        usage_retention_days=None,
        activity_retention_days=None,
    )

    assert settings.usage_retention_days is None
    assert settings.activity_retention_days is None


def test_trace_retention_defaults_and_validates() -> None:
    settings = Settings(
        BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
        BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
    )

    assert settings.trace_retention_days == 30

    with pytest.raises(ValueError, match="greater than or equal to 1"):
        Settings(
            BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
            BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
            BAB_TRACE_RETENTION_DAYS=0,
        )
