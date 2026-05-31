from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.auth.internal.models import Team
from app.modules.keys.internal.models import Allocation, Project, VirtualKey
from app.modules.providers.internal.models import CredentialPool, Provider, ProviderCredential
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.internal.models import AllocationReservation, UsageRecord
from app.modules.usage.schemas import (
    AllocationBudgetBurnRow,
    AllocationReservationSummary,
    AllocationUsageSummary,
    OrganizationUsageSummary,
    RecordAllocationReservation,
    RecordUsage,
    SpendInsights,
    UsageBreakdownRow,
    UsageRecordResponse,
    UsageSummaryTotals,
    UsageTimeSeriesPoint,
    VirtualKeyUsageSummary,
)


async def create_usage_record(*, payload: RecordUsage, db: AsyncSession) -> UsageRecord:
    data = payload.model_dump()
    data["request_id"] = data["request_id"] or current_request_id()
    usage_record = UsageRecord(**data)
    db.add(usage_record)
    await db.flush()
    return usage_record


async def create_allocation_reservation(
    *,
    payload: RecordAllocationReservation,
    db: AsyncSession,
) -> AllocationReservation:
    data = payload.model_dump()
    data["request_id"] = data["request_id"] or current_request_id()
    reservation = AllocationReservation(**data)
    db.add(reservation)
    await db.flush()
    return reservation


async def summarize_active_allocation_reservations(
    *,
    allocation_id: UUID,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> AllocationReservationSummary:
    filters = [
        AllocationReservation.allocation_id == allocation_id,
        AllocationReservation.status == "active",
        AllocationReservation.expires_at > now,
    ]
    if since is not None:
        filters.append(AllocationReservation.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(AllocationReservation.id),
                func.coalesce(func.sum(AllocationReservation.reserved_prompt_tokens), 0),
                func.coalesce(func.sum(AllocationReservation.reserved_completion_tokens), 0),
                func.coalesce(func.sum(AllocationReservation.reserved_total_tokens), 0),
                func.coalesce(func.sum(AllocationReservation.reserved_cost_cents), 0),
            ).where(*filters)
        )
    ).one()
    return AllocationReservationSummary(
        requests=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        cost_cents=int(row[4]),
    )


async def commit_allocation_reservations(
    *,
    reservation_ids: list[UUID],
    usage: UsageAccounting,
    cost_cents: int | None,
    db: AsyncSession,
) -> None:
    if not reservation_ids:
        return
    await db.execute(
        update(AllocationReservation)
        .where(
            AllocationReservation.id.in_(reservation_ids),
            AllocationReservation.status == "active",
        )
        .values(
            status="committed",
            actual_prompt_tokens=usage.prompt_tokens,
            actual_completion_tokens=usage.completion_tokens,
            actual_total_tokens=usage.total_tokens,
            actual_cost_cents=cost_cents,
        )
    )


async def release_allocation_reservations(
    *,
    reservation_ids: list[UUID],
    db: AsyncSession,
) -> None:
    if not reservation_ids:
        return
    await db.execute(
        update(AllocationReservation)
        .where(
            AllocationReservation.id.in_(reservation_ids),
            AllocationReservation.status == "active",
        )
        .values(status="released")
    )


async def list_usage_records(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    provider_id: UUID | None,
    project_id: UUID | None,
    allocation_id: UUID | None,
    virtual_key_id: UUID | None,
    model: str | None,
    limit: int,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    filters = [UsageRecord.org_id == org_id]
    if since is not None:
        filters.append(UsageRecord.created_at >= since)
    if until is not None:
        filters.append(UsageRecord.created_at <= until)
    if team_id is not None:
        filters.append(UsageRecord.team_id == team_id)
    if provider_id is not None:
        filters.append(UsageRecord.provider_id == provider_id)
    if project_id is not None:
        filters.append(UsageRecord.project_id == project_id)
    if allocation_id is not None:
        filters.append(UsageRecord.allocation_id == allocation_id)
    if virtual_key_id is not None:
        filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    if model:
        filters.append(UsageRecord.provider_model == model)
    result = await db.execute(
        select(UsageRecord, ProviderCredential.name, ProviderCredential.key_prefix)
        .outerjoin(ProviderCredential, ProviderCredential.id == UsageRecord.provider_credential_id)
        .where(*filters)
        .order_by(UsageRecord.created_at.desc())
        .limit(limit)
    )
    return [
        UsageRecordResponse.model_validate(
            {
                **record.__dict__,
                "provider_credential_name": credential_name,
                "provider_credential_prefix": credential_prefix,
            }
        )
        for record, credential_name, credential_prefix in result
    ]


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
    until: datetime | None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    base_filters = [UsageRecord.org_id == org_id]
    if since is not None:
        base_filters.append(UsageRecord.created_at >= since)
    if until is not None:
        base_filters.append(UsageRecord.created_at <= until)
    if team_id is not None:
        base_filters.append(UsageRecord.team_id == team_id)
    if provider_id is not None:
        base_filters.append(UsageRecord.provider_id == provider_id)
    if project_id is not None:
        base_filters.append(UsageRecord.project_id == project_id)
    if virtual_key_id is not None:
        base_filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    if model:
        base_filters.append(UsageRecord.provider_model == model)
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


async def get_organization_usage_timeseries(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    grain: str,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    db: AsyncSession,
) -> list[UsageTimeSeriesPoint]:
    filters = [UsageRecord.org_id == org_id]
    if since is not None:
        filters.append(UsageRecord.created_at >= since)
    if until is not None:
        filters.append(UsageRecord.created_at <= until)
    if team_id is not None:
        filters.append(UsageRecord.team_id == team_id)
    if provider_id is not None:
        filters.append(UsageRecord.provider_id == provider_id)
    if project_id is not None:
        filters.append(UsageRecord.project_id == project_id)
    if virtual_key_id is not None:
        filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    if model:
        filters.append(UsageRecord.provider_model == model)
    records = (
        await db.scalars(select(UsageRecord).where(*filters).order_by(UsageRecord.created_at.asc()))
    ).all()
    buckets: dict[datetime, list[UsageRecord]] = {}
    for record in records:
        bucket = _bucket_datetime(record.created_at, grain)
        buckets.setdefault(bucket, []).append(record)
    return [
        UsageTimeSeriesPoint(
            bucket=bucket,
            **_records_to_totals(bucket_records).model_dump(),
        )
        for bucket, bucket_records in sorted(buckets.items())
    ]


async def get_spend_insights(
    *,
    org_id: UUID,
    window: str,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    provider_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    model: str | None,
    db: AsyncSession,
) -> SpendInsights:
    filters = [UsageRecord.org_id == org_id]
    if since is not None:
        filters.append(UsageRecord.created_at >= since)
    if until is not None:
        filters.append(UsageRecord.created_at <= until)
    if team_id is not None:
        filters.append(UsageRecord.team_id == team_id)
    if provider_id is not None:
        filters.append(UsageRecord.provider_id == provider_id)
    if project_id is not None:
        filters.append(UsageRecord.project_id == project_id)
    if virtual_key_id is not None:
        filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    if model:
        filters.append(UsageRecord.provider_model == model)
    top_spend_drivers = await _breakdown(
        UsageRecord.provider_model,
        UsageRecord.provider_model,
        *filters,
        db=db,
    )
    return SpendInsights(
        window=window,
        top_spend_drivers=sorted(
            top_spend_drivers,
            key=lambda row: row.cost_cents,
            reverse=True,
        )[:10],
        allocation_budget_burn=await _allocation_budget_burn(
            org_id=org_id,
            since=since,
            until=until,
            team_id=team_id,
            provider_id=provider_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            model=model,
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


async def _allocation_budget_burn(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    db: AsyncSession,
) -> list[AllocationBudgetBurnRow]:
    usage_filters = [UsageRecord.allocation_id == Allocation.id]
    if since is not None:
        usage_filters.append(UsageRecord.created_at >= since)
    if until is not None:
        usage_filters.append(UsageRecord.created_at <= until)
    if team_id is not None:
        usage_filters.append(UsageRecord.team_id == team_id)
    if provider_id is not None:
        usage_filters.append(UsageRecord.provider_id == provider_id)
    if project_id is not None:
        usage_filters.append(UsageRecord.project_id == project_id)
    if virtual_key_id is not None:
        usage_filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    if model:
        usage_filters.append(UsageRecord.provider_model == model)
    spent_subquery = (
        select(func.coalesce(func.sum(UsageRecord.cost_cents), 0))
        .where(*usage_filters)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(
                Allocation.id,
                Allocation.name,
                Allocation.target_type,
                Allocation.window,
                Allocation.budget_cents,
                spent_subquery,
            )
            .where(
                Allocation.org_id == org_id,
                Allocation.budget_cents.is_not(None),
                Allocation.is_active.is_(True),
            )
            .order_by(spent_subquery.desc(), Allocation.name.asc())
            .limit(20)
        )
    ).all()
    return [
        AllocationBudgetBurnRow(
            allocation_id=row[0],
            allocation_name=row[1],
            target_type=row[2],
            window=row[3],
            budget_cents=int(row[4]),
            spent_cents=int(row[5]),
            remaining_cents=max(0, int(row[4]) - int(row[5])),
            burn_rate_pct=round((int(row[5]) / int(row[4])) * 100, 1) if int(row[4]) > 0 else 0,
        )
        for row in rows
    ]


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


def _bucket_datetime(value: datetime, grain: str) -> datetime:
    if grain == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    if grain == "week":
        day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start.replace(day=day_start.day) - timedelta(days=day_start.weekday())
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _records_to_totals(records: list[UsageRecord]) -> UsageSummaryTotals:
    requests = len(records)
    successful_requests = sum(1 for record in records if record.http_status < 400)
    failed_requests = requests - successful_requests
    latencies = [record.latency_ms for record in records if record.latency_ms is not None]
    return UsageSummaryTotals(
        requests=requests,
        successful_requests=successful_requests,
        failed_requests=failed_requests,
        prompt_tokens=sum(record.prompt_tokens or 0 for record in records),
        completion_tokens=sum(record.completion_tokens or 0 for record in records),
        total_tokens=sum(record.total_tokens or 0 for record in records),
        cost_cents=sum(record.cost_cents or 0 for record in records),
        average_latency_ms=round(sum(latencies) / len(latencies)) if latencies else None,
    )
