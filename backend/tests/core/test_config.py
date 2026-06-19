import pytest

from app.core.config import Settings, validate_runtime_settings


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
