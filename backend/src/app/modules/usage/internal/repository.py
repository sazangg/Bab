from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import String, case, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.auth.internal.models import Team
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.policies.internal.models import AccessPolicy, LimitPolicy, LimitPolicyRule
from app.modules.providers.internal.models import CredentialPool, Provider, ProviderCredential
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.internal.models import LimitPolicyReservation, UsageRecord
from app.modules.usage.schemas import (
    LimitPolicyBudgetBurnRow,
    LimitPolicyReservationSummary,
    OrganizationUsageSummary,
    RecordLimitPolicyReservation,
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


async def create_limit_policy_reservation(
    *,
    payload: RecordLimitPolicyReservation,
    db: AsyncSession,
) -> LimitPolicyReservation:
    data = payload.model_dump()
    data["request_id"] = data["request_id"] or current_request_id()
    reservation = LimitPolicyReservation(**data)
    db.add(reservation)
    await db.flush()
    return reservation


async def summarize_active_limit_policy_reservations(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None,
    limit_policy_assignment_id: UUID | None,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    filters = [
        LimitPolicyReservation.limit_policy_id == limit_policy_id,
        LimitPolicyReservation.status == "active",
        LimitPolicyReservation.expires_at > now,
    ]
    if limit_policy_rule_id is not None:
        filters.append(LimitPolicyReservation.limit_policy_rule_id == limit_policy_rule_id)
    if limit_policy_assignment_id is not None:
        filters.append(
            LimitPolicyReservation.limit_policy_assignment_id == limit_policy_assignment_id
        )
    if since is not None:
        filters.append(LimitPolicyReservation.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(LimitPolicyReservation.id),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_prompt_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_completion_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_total_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_cost_cents), 0),
            ).where(*filters)
        )
    ).one()
    return LimitPolicyReservationSummary(
        requests=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        cost_cents=int(row[4]),
    )


async def summarize_active_virtual_key_reservations(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    filters = [
        LimitPolicyReservation.virtual_key_id == virtual_key_id,
        LimitPolicyReservation.status == "active",
        LimitPolicyReservation.expires_at > now,
    ]
    if since is not None:
        filters.append(LimitPolicyReservation.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(LimitPolicyReservation.id),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_prompt_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_completion_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_total_tokens), 0),
                func.coalesce(func.sum(LimitPolicyReservation.reserved_cost_cents), 0),
            ).where(*filters)
        )
    ).one()
    return LimitPolicyReservationSummary(
        requests=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        cost_cents=int(row[4]),
    )


async def commit_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    usage: UsageAccounting,
    cost_cents: int | None,
    db: AsyncSession,
) -> None:
    if not reservation_ids:
        return
    await db.execute(
        update(LimitPolicyReservation)
        .where(
            LimitPolicyReservation.id.in_(reservation_ids),
            LimitPolicyReservation.status == "active",
        )
        .values(
            status="committed",
            actual_prompt_tokens=usage.prompt_tokens,
            actual_completion_tokens=usage.completion_tokens,
            actual_total_tokens=usage.total_tokens,
            actual_cost_cents=cost_cents,
        )
    )


async def release_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    db: AsyncSession,
) -> None:
    if not reservation_ids:
        return
    await db.execute(
        update(LimitPolicyReservation)
        .where(
            LimitPolicyReservation.id.in_(reservation_ids),
            LimitPolicyReservation.status == "active",
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
    virtual_key_id: UUID | None,
    model: str | None,
    limit: int | None,
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
    if virtual_key_id is not None:
        filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    if model:
        filters.append(UsageRecord.provider_model == model)
    query = (
        select(UsageRecord, ProviderCredential.name, ProviderCredential.key_prefix)
        .outerjoin(ProviderCredential, ProviderCredential.id == UsageRecord.provider_credential_id)
        .where(*filters)
        .order_by(UsageRecord.created_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
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


async def summarize_limit_policy_usage(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None,
    limit_policy_assignment_id: UUID | None,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int]:
    filters = [cast(UsageRecord.limit_policy_ids, String).contains(str(limit_policy_id))]
    if limit_policy_rule_id is not None:
        filters.append(
            cast(UsageRecord.limit_policy_rule_ids, String).contains(str(limit_policy_rule_id))
        )
    if limit_policy_assignment_id is not None:
        filters.append(
            cast(UsageRecord.limit_policy_assignment_ids, String).contains(
                str(limit_policy_assignment_id)
            )
        )
    if since is not None:
        filters.append(UsageRecord.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(UsageRecord.id),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
            ).where(*filters)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2]), int(row[3])


async def summarize_virtual_key_usage(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int]:
    query = select(
        func.count(UsageRecord.id),
        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
        func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0),
    ).where(UsageRecord.virtual_key_id == virtual_key_id)
    if since is not None:
        query = query.where(UsageRecord.created_at >= since)
    row = (await db.execute(query)).one()
    return int(row[0]), int(row[1]), int(row[2]), int(row[3])


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
        by_access_policy=await _breakdown(
            UsageRecord.access_policy_id,
            AccessPolicy.name,
            *filters,
            join_model=AccessPolicy,
            join_on=AccessPolicy.id == UsageRecord.access_policy_id,
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
        limit_policy_budget_burn=await _limit_policy_budget_burn(
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
        by_access_policy=await _breakdown(
            UsageRecord.access_policy_id,
            AccessPolicy.name,
            *base_filters,
            join_model=AccessPolicy,
            join_on=AccessPolicy.id == UsageRecord.access_policy_id,
            db=db,
        ),
    )


async def _limit_policy_budget_burn(
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
) -> list[LimitPolicyBudgetBurnRow]:
    rules = (
        await db.scalars(
            select(LimitPolicyRule)
            .join(LimitPolicy, LimitPolicy.id == LimitPolicyRule.limit_policy_id)
            .where(
                LimitPolicyRule.org_id == org_id,
                LimitPolicyRule.limit_type == "budget_cents",
                LimitPolicyRule.is_active.is_(True),
                LimitPolicy.is_active.is_(True),
            )
            .order_by(LimitPolicyRule.name.asc())
        )
    ).all()
    rows: list[LimitPolicyBudgetBurnRow] = []
    for rule in rules:
        policy = await db.get(LimitPolicy, rule.limit_policy_id)
        if policy is None:
            continue
        filters = [
            UsageRecord.org_id == org_id,
            cast(UsageRecord.limit_policy_ids, String).contains(str(rule.limit_policy_id)),
            cast(UsageRecord.limit_policy_rule_ids, String).contains(str(rule.id)),
        ]
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
        spent_query = select(func.coalesce(func.sum(UsageRecord.cost_cents), 0)).where(*filters)
        spent = (await db.scalar(spent_query)) or 0
        rows.append(
            LimitPolicyBudgetBurnRow(
                limit_policy_id=rule.limit_policy_id,
                limit_policy_rule_id=rule.id,
                limit_policy_name=policy.name,
                rule_name=rule.name,
                interval=format_limit_rule_interval(
                    interval_unit=rule.interval_unit,
                    interval_count=rule.interval_count,
                ),
                budget_cents=int(rule.limit_value),
                spent_cents=int(spent),
                remaining_cents=max(0, int(rule.limit_value) - int(spent)),
                burn_rate_pct=round((int(spent) / int(rule.limit_value or 1)) * 100, 1),
            )
        )
    return sorted(rows, key=lambda row: row.spent_cents, reverse=True)[:20]


def format_limit_rule_interval(*, interval_unit: str, interval_count: int) -> str:
    if interval_unit == "lifetime":
        return "lifetime"
    return f"{interval_count} {interval_unit}{'' if interval_count == 1 else 's'}"


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
