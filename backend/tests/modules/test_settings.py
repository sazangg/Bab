from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import Scope
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
