from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings.internal.models import OrganizationSettings


async def get_settings(*, org_id: UUID, db: AsyncSession) -> OrganizationSettings | None:
    return await db.scalar(
        select(OrganizationSettings).where(OrganizationSettings.org_id == org_id)
    )


async def create_settings(
    *,
    org_id: UUID,
    organization_name: str,
    default_max_body_bytes: int,
    db: AsyncSession,
) -> OrganizationSettings:
    settings = OrganizationSettings(
        org_id=org_id,
        organization_name=organization_name,
        default_max_body_bytes=default_max_body_bytes,
    )
    db.add(settings)
    await db.flush()
    return settings
