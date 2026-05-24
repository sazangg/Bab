from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Team
from app.modules.keys.internal.models import Allocation, Project, VirtualKey
from app.modules.providers.internal.models import CredentialPool, Provider
from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.schemas import (
    AllocationUsageSummary,
    OrganizationUsageSummary,
    RecordUsage,
    UsageBreakdownRow,
    UsageSummaryTotals,
    VirtualKeyUsageSummary,
)


async def create_usage_record(*, payload: RecordUsage, db: AsyncSession) -> UsageRecord:
    usage_record = UsageRecord(**payload.model_dump())
    db.add(usage_record)
    await db.flush()
    return usage_record


async def list_usage_records(
    *,
    org_id: UUID,
    since: datetime | None,
    provider_id: UUID | None,
    project_id: UUID | None,
    allocation_id: UUID | None,
    virtual_key_id: UUID | None,
    limit: int,
    db: AsyncSession,
) -> list[UsageRecord]:
    filters = [UsageRecord.org_id == org_id]
    if since is not None:
        filters.append(UsageRecord.created_at >= since)
    if provider_id is not None:
        filters.append(UsageRecord.provider_id == provider_id)
    if project_id is not None:
        filters.append(UsageRecord.project_id == project_id)
    if allocation_id is not None:
        filters.append(UsageRecord.allocation_id == allocation_id)
    if virtual_key_id is not None:
        filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    result = await db.scalars(
        select(UsageRecord).where(*filters).order_by(UsageRecord.created_at.desc()).limit(limit)
    )
    return list(result)


async def summarize_allocation_usage(
    *,
    allocation_id: UUID,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int]:
    query = select(
        func.count(UsageRecord.id),
        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
        func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
        func.coalesce(func.sum(UsageRecord.cost_cents), 0),
    ).where(UsageRecord.allocation_id == allocation_id)
    if since is not None:
        query = query.where(UsageRecord.created_at >= since)
    row = (await db.execute(query)).one()
    return int(row[0]), int(row[1]), int(row[2]), int(row[3])


async def get_allocation_usage_summary(
    *,
    allocation_id: UUID,
    org_id: UUID,
    window: str,
    since: datetime | None,
    db: AsyncSession,
) -> AllocationUsageSummary:
    base_filters_list = [UsageRecord.org_id == org_id, UsageRecord.allocation_id == allocation_id]
    if since is not None:
        base_filters_list.append(UsageRecord.created_at >= since)
    base_filters = tuple(base_filters_list)
    return AllocationUsageSummary(
        allocation_id=allocation_id,
        window=window,
        totals=await _totals(*base_filters, db=db),
        by_virtual_key=await _breakdown(
            UsageRecord.virtual_key_id,
            VirtualKey.name,
            *base_filters,
            join_model=VirtualKey,
            join_on=VirtualKey.id == UsageRecord.virtual_key_id,
            db=db,
        ),
        by_provider=await _breakdown(
            UsageRecord.provider_id,
            Provider.name,
            *base_filters,
            join_model=Provider,
            join_on=Provider.id == UsageRecord.provider_id,
            db=db,
        ),
        by_model=await _breakdown(
            UsageRecord.provider_model,
            UsageRecord.provider_model,
            *base_filters,
            db=db,
        ),
        by_pool=await _breakdown(
            UsageRecord.pool_id,
            CredentialPool.name,
            *base_filters,
            join_model=CredentialPool,
            join_on=CredentialPool.id == UsageRecord.pool_id,
            db=db,
        ),
    )


async def get_organization_usage_summary(
    *,
    org_id: UUID,
    window: str,
    since: datetime | None,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    base_filters = [UsageRecord.org_id == org_id]
    if since is not None:
        base_filters.append(UsageRecord.created_at >= since)
    filters = tuple(base_filters)
    return OrganizationUsageSummary(
        window=window,
        totals=await _totals(*filters, db=db),
        by_provider=await _breakdown(
            UsageRecord.provider_id,
            Provider.name,
            *filters,
            join_model=Provider,
            join_on=Provider.id == UsageRecord.provider_id,
            db=db,
        ),
        by_model=await _breakdown(
            UsageRecord.provider_model,
            UsageRecord.provider_model,
            *filters,
            db=db,
        ),
        by_pool=await _breakdown(
            UsageRecord.pool_id,
            CredentialPool.name,
            *filters,
            join_model=CredentialPool,
            join_on=CredentialPool.id == UsageRecord.pool_id,
            db=db,
        ),
        by_team=await _breakdown(
            UsageRecord.team_id,
            Team.name,
            *filters,
            join_model=Team,
            join_on=Team.id == UsageRecord.team_id,
            db=db,
        ),
        by_project=await _breakdown(
            UsageRecord.project_id,
            Project.name,
            *filters,
            join_model=Project,
            join_on=Project.id == UsageRecord.project_id,
            db=db,
        ),
        by_allocation=await _breakdown(
            UsageRecord.allocation_id,
            Allocation.name,
            *filters,
            join_model=Allocation,
            join_on=Allocation.id == UsageRecord.allocation_id,
            db=db,
        ),
        by_virtual_key=await _breakdown(
            UsageRecord.virtual_key_id,
            VirtualKey.name,
            *filters,
            join_model=VirtualKey,
            join_on=VirtualKey.id == UsageRecord.virtual_key_id,
            db=db,
        ),
    )


async def get_virtual_key_usage_summary(
    *,
    virtual_key_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> VirtualKeyUsageSummary:
    base_filters = (UsageRecord.org_id == org_id, UsageRecord.virtual_key_id == virtual_key_id)
    return VirtualKeyUsageSummary(
        virtual_key_id=virtual_key_id,
        totals=await _totals(*base_filters, db=db),
        by_provider=await _breakdown(
            UsageRecord.provider_id,
            Provider.name,
            *base_filters,
            join_model=Provider,
            join_on=Provider.id == UsageRecord.provider_id,
            db=db,
        ),
        by_model=await _breakdown(
            UsageRecord.provider_model,
            UsageRecord.provider_model,
            *base_filters,
            db=db,
        ),
        by_pool=await _breakdown(
            UsageRecord.pool_id,
            CredentialPool.name,
            *base_filters,
            join_model=CredentialPool,
            join_on=CredentialPool.id == UsageRecord.pool_id,
            db=db,
        ),
        by_allocation=await _breakdown(
            UsageRecord.allocation_id,
            Allocation.name,
            *base_filters,
            join_model=Allocation,
            join_on=Allocation.id == UsageRecord.allocation_id,
            db=db,
        ),
    )


async def _totals(*filters, db: AsyncSession) -> UsageSummaryTotals:
    row = (
        await db.execute(
            select(
                func.count(UsageRecord.id),
                func.coalesce(
                    func.sum(case((UsageRecord.http_status < 400, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((UsageRecord.http_status >= 400, 1), else_=0)),
                    0,
                ),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
                func.avg(UsageRecord.latency_ms),
            ).where(*filters)
        )
    ).one()
    return _row_to_totals(row)


async def _breakdown(
    group_column,
    label_column,
    *filters,
    db: AsyncSession,
    join_model=None,
    join_on=None,
) -> list[UsageBreakdownRow]:
    query = select(
        group_column,
        label_column,
        func.count(UsageRecord.id),
        func.coalesce(func.sum(case((UsageRecord.http_status < 400, 1), else_=0)), 0),
        func.coalesce(func.sum(case((UsageRecord.http_status >= 400, 1), else_=0)), 0),
        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
        func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0),
        func.coalesce(func.sum(UsageRecord.cost_cents), 0),
        func.avg(UsageRecord.latency_ms),
    ).where(*filters)
    if join_model is not None and join_on is not None:
        query = query.join(join_model, join_on)
    query = query.group_by(group_column, label_column).order_by(func.count(UsageRecord.id).desc())
    rows = (await db.execute(query)).all()
    return [_row_to_breakdown(row) for row in rows]


def _row_to_totals(row) -> UsageSummaryTotals:
    return UsageSummaryTotals(
        requests=int(row[0]),
        successful_requests=int(row[1]),
        failed_requests=int(row[2]),
        prompt_tokens=int(row[3]),
        completion_tokens=int(row[4]),
        total_tokens=int(row[5]),
        cost_cents=int(row[6]),
        average_latency_ms=None if row[7] is None else round(row[7]),
    )


def _row_to_breakdown(row) -> UsageBreakdownRow:
    return UsageBreakdownRow(
        id=str(row[0]),
        label=str(row[1]),
        requests=int(row[2]),
        successful_requests=int(row[3]),
        failed_requests=int(row[4]),
        prompt_tokens=int(row[5]),
        completion_tokens=int(row[6]),
        total_tokens=int(row[7]),
        cost_cents=int(row[8]),
        average_latency_ms=None if row[9] is None else round(row[9]),
    )
