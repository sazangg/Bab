from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workspace.internal import repository


async def ensure_organization_active(*, org_id: UUID, db: AsyncSession) -> None:
    await repository.ensure_organization_active(org_id=org_id, db=db)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
