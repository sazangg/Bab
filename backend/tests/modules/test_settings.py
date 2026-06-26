import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import Scope
from app.modules.activity.internal.models import ActivityEvent
from app.modules.audit.internal.models import AuditEvent
from app.modules.auth.internal.models import Organization
from app.modules.auth.internal.service import MOCK_ADMIN_ID
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.settings import facade
from app.modules.settings.internal.models import OrganizationSettings
from app.modules.settings.schemas import UpdateOrganizationSettingsRequest


async def test_settings_created_from_environment_defaults(db_session: AsyncSession):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()

    response = await facade.get_organization_settings(scope=Scope(org_id=org.id), db=db_session)

    assert response.organization_name == "Acme"
    assert response.default_max_body_bytes == settings.proxy_max_body_bytes
    assert response.deployment_max_body_bytes == settings.proxy_max_body_bytes
    assert response.usage_retention_days == settings.usage_retention_days
    assert response.activity_retention_days == settings.activity_retention_days
    stored = await db_session.scalar(
        select(OrganizationSettings).where(OrganizationSettings.org_id == org.id)
    )
    assert stored is not None


async def test_settings_update_syncs_organization_name(db_session: AsyncSession):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=MOCK_ADMIN_ID,
        org_id=org.id,
        team_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )

    response = await facade.update_organization_settings(
        payload=UpdateOrganizationSettingsRequest(
            organization_name="Bab Labs",
            default_retry_count=2,
            allow_secret_copy=False,
        ),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    await db_session.refresh(org)

    assert response.organization_name == "Bab Labs"
    assert response.default_retry_count == 2
    assert response.allow_secret_copy is False
    assert org.name == "Bab Labs"


async def test_settings_update_records_changed_fields_metadata(db_session: AsyncSession):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=MOCK_ADMIN_ID,
        org_id=org.id,
        team_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )

    await facade.update_organization_settings(
        payload=UpdateOrganizationSettingsRequest(
            organization_name="Bab Labs",
            public_base_url="https://gateway.example.com/",
            default_retry_count=2,
        ),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    activity = await db_session.scalar(
        select(ActivityEvent).where(ActivityEvent.action == "settings.updated")
    )
    audit = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "settings.updated")
    )
    assert activity is not None
    assert audit is not None
    assert activity.metadata_["changed_fields"] == [
        "default_retry_count",
        "organization_name",
        "public_base_url",
    ]
    assert audit.metadata_["changed_fields"] == activity.metadata_["changed_fields"]
    assert activity.metadata_["changes"]["organization_name"] == {
        "old": "Acme",
        "new": "Bab Labs",
    }
    assert activity.metadata_["changes"]["public_base_url"] == {
        "old": None,
        "new": "https://gateway.example.com",
    }
    assert activity.metadata_["changes"]["default_retry_count"] == {"old": 0, "new": 2}
    assert audit.metadata_["changes"] == activity.metadata_["changes"]


def test_public_base_url_is_normalized_and_validated():
    payload = UpdateOrganizationSettingsRequest(public_base_url=" https://gateway.example.com/ ")

    assert payload.public_base_url == "https://gateway.example.com"

    assert UpdateOrganizationSettingsRequest(public_base_url="").public_base_url is None
    assert UpdateOrganizationSettingsRequest(public_base_url=None).public_base_url is None

    for value in [
        "gateway.example.com",
        "ftp://gateway.example.com",
        "/api",
        "https://gateway.example.com/v1",
        "https://gateway.example.com?x=1",
        "https://gateway.example.com#docs",
        "https://user:pass@gateway.example.com",
    ]:
        try:
            UpdateOrganizationSettingsRequest(public_base_url=value)
        except ValidationError:
            continue
        raise AssertionError(f"{value} should be rejected")


def test_public_app_url_is_normalized_and_validated():
    payload = UpdateOrganizationSettingsRequest(public_app_url=" https://app.example.com/ ")

    assert payload.public_app_url == "https://app.example.com"

    assert UpdateOrganizationSettingsRequest(public_app_url="").public_app_url is None
    assert UpdateOrganizationSettingsRequest(public_app_url=None).public_app_url is None

    for value in [
        "app.example.com",
        "ftp://app.example.com",
        "/app",
        "https://app.example.com/invites",
        "https://app.example.com?x=1",
        "https://app.example.com#invite",
        "https://user:pass@app.example.com",
    ]:
        try:
            UpdateOrganizationSettingsRequest(public_app_url=value)
        except ValidationError:
            continue
        raise AssertionError(f"{value} should be rejected")


def test_non_nullable_settings_reject_explicit_null():
    for field in [
        "organization_name",
        "default_request_timeout_seconds",
        "default_retry_count",
        "default_max_body_bytes",
        "default_model_sync_mode",
        "virtual_key_prefix",
        "allow_secret_copy",
    ]:
        with pytest.raises(ValidationError):
            UpdateOrganizationSettingsRequest.model_validate({field: None})


def test_default_max_body_bytes_cannot_exceed_deployment_limit(monkeypatch):
    monkeypatch.setattr(settings, "proxy_max_body_bytes", 10_000)

    assert UpdateOrganizationSettingsRequest(default_max_body_bytes=10_000)
    with pytest.raises(ValidationError):
        UpdateOrganizationSettingsRequest(default_max_body_bytes=10_001)
