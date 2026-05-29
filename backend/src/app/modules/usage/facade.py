from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal import repository
from app.modules.usage.schemas import (
    AllocationUsageSummary,
    OrganizationUsageSummary,
    RecordUsage,
    SpendInsights,
    UsageRecordResponse,
    UsageTimeSeriesPoint,
    VirtualKeyUsageSummary,
)


async def record_usage(*, payload: RecordUsage, db: AsyncSession) -> None:
    await repository.create_usage_record(payload=payload, db=db)
    await db.commit()


async def list_usage_records(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    allocation_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    limit: int = 100,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    records = await repository.list_usage_records(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        allocation_id=allocation_id,
        virtual_key_id=virtual_key_id,
        model=model,
        limit=limit,
        db=db,
    )
    return records


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
    window: str = "lifetime",
    db: AsyncSession,
) -> AllocationUsageSummary:
    return await repository.get_allocation_usage_summary(
        allocation_id=allocation_id,
        org_id=org_id,
        window=window,
        since=allocation_window_start(window),
        db=db,
    )


async def get_organization_usage_summary(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    return await repository.get_organization_usage_summary(
        org_id=org_id,
        window=window,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        db=db,
    )


async def get_organization_usage_timeseries(
    *,
    org_id: UUID,
    window: str,
    grain: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    db: AsyncSession,
) -> list[UsageTimeSeriesPoint]:
    return await repository.get_organization_usage_timeseries(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        grain=grain,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        db=db,
    )


async def get_spend_insights(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    db: AsyncSession,
) -> SpendInsights:
    return await repository.get_spend_insights(
        org_id=org_id,
        window=window,
        since=start_at or window_start(window),
        until=end_at,
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
    if window == "90d":
        return now - timedelta(days=90)
    return None


def allocation_window_start(window: str) -> datetime | None:
    now = datetime.now(UTC)
    if window == "daily":
        return now - timedelta(days=1)
    if window == "weekly":
        return now - timedelta(days=7)
    if window == "monthly":
        return now - timedelta(days=30)
    return None
