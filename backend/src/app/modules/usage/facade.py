from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal import repository
from app.modules.usage.schemas import (
    AllocationUsageSummary,
    OrganizationUsageSummary,
    RecordUsage,
    VirtualKeyUsageSummary,
)


async def record_usage(*, payload: RecordUsage, db: AsyncSession) -> None:
    await repository.create_usage_record(payload=payload, db=db)
    await db.commit()


async def summarize_allocation_usage(
    *,
    allocation_id: UUID,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int]:
    return await repository.summarize_allocation_usage(
        allocation_id=allocation_id,
        since=since,
        db=db,
    )


async def get_allocation_usage_summary(
    *,
    allocation_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> AllocationUsageSummary:
    return await repository.get_allocation_usage_summary(
        allocation_id=allocation_id,
        org_id=org_id,
        db=db,
    )


async def get_organization_usage_summary(
    *,
    org_id: UUID,
    window: str,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    return await repository.get_organization_usage_summary(
        org_id=org_id,
        window=window,
        since=window_start(window),
        db=db,
    )


async def get_virtual_key_usage_summary(
    *,
    virtual_key_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> VirtualKeyUsageSummary:
    return await repository.get_virtual_key_usage_summary(
        virtual_key_id=virtual_key_id,
        org_id=org_id,
        db=db,
    )


def window_start(window: str) -> datetime | None:
    now = datetime.now(UTC)
    if window == "24h":
        return now - timedelta(hours=24)
    if window == "7d":
        return now - timedelta(days=7)
    if window == "30d":
        return now - timedelta(days=30)
    return None
