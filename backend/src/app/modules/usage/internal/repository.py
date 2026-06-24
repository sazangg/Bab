import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Integer, case, cast, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.request_ids import current_request_id
from app.modules.policies.internal.models import LimitPolicy, LimitPolicyRule
from app.modules.policy_kernel.models import Policy
from app.modules.providers.internal.models import CredentialPool, Provider, ProviderCredential
from app.modules.usage.accounting import UsageAccounting, subtract_months
from app.modules.usage.internal.models import (
    GatewayPolicyDecision,
    GatewayRequest,
    GatewayRouteAttempt,
    LimitPolicyCommittedUsage,
    LimitPolicyReservation,
    UsageRecord,
)
from app.modules.usage.schemas import (
    CreateGatewayRequest,
    FinalizeGatewayRequest,
    GatewayRequestResolvedSubject,
    LimitPolicyBudgetBurnRow,
    LimitPolicyReservationSummary,
    OrganizationUsageSummary,
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
    RecordUsage,
    SpendInsights,
    UsageBreakdownRow,
    UsageFilterOptions,
    UsageRecentError,
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


async def create_limit_policy_committed_usage(
    *, payload: RecordLimitPolicyCommittedUsage, db: AsyncSession
) -> LimitPolicyCommittedUsage:
    committed_usage = LimitPolicyCommittedUsage(**payload.model_dump())
    db.add(committed_usage)
    await db.flush()
    return committed_usage


async def create_gateway_request(
    *,
    payload: CreateGatewayRequest,
    db: AsyncSession,
) -> GatewayRequest:
    data = payload.model_dump()
    data["request_id"] = data["request_id"] or current_request_id()
    started_at = data.get("started_at") or datetime.now(UTC)
    data["started_at"] = started_at
    data["trace_expires_at"] = started_at + timedelta(days=settings.trace_retention_days)
    gateway_request = GatewayRequest(**data)
    db.add(gateway_request)
    await db.flush()
    return gateway_request


async def finalize_gateway_request(
    *,
    gateway_request_id: UUID,
    payload: FinalizeGatewayRequest,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRequest)
        .where(GatewayRequest.id == gateway_request_id)
        .values(**payload.model_dump(), completed_at=datetime.now(UTC))
    )


async def attach_gateway_request_subject(
    *,
    gateway_request_id: UUID,
    subject: GatewayRequestResolvedSubject,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRequest)
        .where(GatewayRequest.id == gateway_request_id)
        .values(
            org_id=subject.org_id,
            team_id=subject.team_id,
            project_id=subject.project_id,
            virtual_key_id=subject.virtual_key_id,
        )
    )


async def attach_gateway_request_resolution(
    *,
    gateway_request_id: UUID,
    values: dict,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRequest)
        .where(GatewayRequest.id == gateway_request_id)
        .values(**values)
    )


async def create_gateway_route_attempt(
    *,
    values: dict,
    db: AsyncSession,
) -> GatewayRouteAttempt:
    attempt = GatewayRouteAttempt(**values)
    db.add(attempt)
    await db.flush()
    return attempt


async def update_gateway_route_attempt(
    *,
    route_attempt_id: UUID,
    values: dict,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRouteAttempt)
        .where(GatewayRouteAttempt.id == route_attempt_id)
        .values(**values)
    )


async def create_gateway_policy_decision(
    *,
    values: dict,
    db: AsyncSession,
) -> GatewayPolicyDecision:
    decision = GatewayPolicyDecision(**values)
    db.add(decision)
    await db.flush()
    return decision


async def get_gateway_request(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> GatewayRequest | None:
    return await db.scalar(
        select(GatewayRequest).where(
            GatewayRequest.id == gateway_request_id,
            GatewayRequest.org_id == org_id,
        )
    )


async def list_gateway_requests(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    provider_id: UUID | None,
    public_model_name: str | None,
    requested_model: str | None,
    request_id: str | None,
    status: str | None,
    fallback: str | None,
    error_code: str | None,
    search: str | None,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
    limit: int,
    offset: int,
    now: datetime,
    db: AsyncSession,
) -> list[GatewayRequest]:
    filters = [
        GatewayRequest.org_id == org_id,
        GatewayRequest.trace_expires_at > now,
    ]
    if since is not None:
        filters.append(GatewayRequest.started_at >= since)
    if until is not None:
        filters.append(GatewayRequest.started_at <= until)
    if team_id is not None:
        filters.append(GatewayRequest.team_id == team_id)
    if project_id is not None:
        filters.append(GatewayRequest.project_id == project_id)
    if virtual_key_id is not None:
        filters.append(GatewayRequest.virtual_key_id == virtual_key_id)
    if provider_id is not None:
        route_attempt_exists = (
            select(1)
            .select_from(GatewayRouteAttempt)
            .where(
                GatewayRouteAttempt.gateway_request_id == GatewayRequest.id,
                GatewayRouteAttempt.provider_id == provider_id,
            )
            .exists()
        )
        filters.append(
            or_(
                GatewayRequest.final_provider_id == provider_id,
                route_attempt_exists,
            )
        )
    if public_model_name:
        filters.append(GatewayRequest.public_model_name == public_model_name.strip())
    if requested_model:
        filters.append(GatewayRequest.requested_model == requested_model.strip())
    if request_id:
        filters.append(GatewayRequest.request_id == request_id.strip())
    if fallback == "attempted":
        filters.append(GatewayRequest.fallback_attempted.is_(True))
    elif fallback == "not_attempted":
        filters.append(GatewayRequest.fallback_attempted.is_(False))
    if error_code:
        filters.append(GatewayRequest.final_error_code == error_code.strip())
    if search:
        term = search.strip()
        filters.append(
            or_(
                GatewayRequest.request_id.icontains(term, autoescape=True),
                GatewayRequest.requested_model.icontains(term, autoescape=True),
                GatewayRequest.public_model_name.icontains(term, autoescape=True),
                GatewayRequest.final_provider_model.icontains(term, autoescape=True),
                GatewayRequest.final_error_code.icontains(term, autoescape=True),
            )
        )
    if status:
        filters.append(_gateway_request_status_filter(status))
    _add_allowed_gateway_request_scope_filters(
        filters,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    result = await db.scalars(
        select(GatewayRequest)
        .where(*filters)
        .order_by(GatewayRequest.started_at.desc(), GatewayRequest.id.desc())
        .limit(limit + 1)
        .offset(offset)
    )
    return list(result)


async def list_gateway_route_attempts(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> list[GatewayRouteAttempt]:
    result = await db.scalars(
        select(GatewayRouteAttempt)
        .where(
            GatewayRouteAttempt.gateway_request_id == gateway_request_id,
            GatewayRouteAttempt.org_id == org_id,
        )
        .order_by(GatewayRouteAttempt.attempt_index, GatewayRouteAttempt.started_at)
    )
    return list(result)


async def list_gateway_policy_decisions(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> list[GatewayPolicyDecision]:
    result = await db.scalars(
        select(GatewayPolicyDecision)
        .where(
            GatewayPolicyDecision.gateway_request_id == gateway_request_id,
            GatewayPolicyDecision.org_id == org_id,
        )
        .order_by(GatewayPolicyDecision.created_at)
    )
    return list(result)


async def list_usage_records_for_gateway_request(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    result = await db.execute(
        select(UsageRecord, ProviderCredential.name, ProviderCredential.key_prefix)
        .outerjoin(ProviderCredential, ProviderCredential.id == UsageRecord.provider_credential_id)
        .where(
            UsageRecord.gateway_request_id == gateway_request_id,
            UsageRecord.org_id == org_id,
        )
        .order_by(UsageRecord.routing_attempt_index, UsageRecord.created_at)
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


async def acquire_limit_scope_lock(*, assignment_id: UUID, db: AsyncSession) -> None:
    # Postgres transaction-scoped advisory lock keyed by the assignment id. Held until
    # the enclosing transaction commits, so the read-decide-reserve sequence runs
    # without interleaving. SQLite has no advisory locks but serializes writers, so
    # the race the lock guards against does not arise there.
    if db.get_bind().dialect.name != "postgresql":
        return
    key = int.from_bytes(
        hashlib.sha256(str(assignment_id).encode()).digest()[:8], "big", signed=True
    )
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def acquire_limit_counter_lock(*, identity: str, db: AsyncSession) -> None:
    # Postgres transaction-scoped advisory lock keyed by the resolved limit counter.
    # Held until commit, so read-decide-reserve is serialized per concrete counter
    # instead of per whole assignment.
    if db.get_bind().dialect.name != "postgresql":
        return
    key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


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
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
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
    if counter_key is not None:
        filters.append(LimitPolicyReservation.counter_key == counter_key)
    if counting_unit is not None:
        filters.append(LimitPolicyReservation.counting_unit == counting_unit)
    if window_descriptor is not None:
        filters.append(
            or_(
                LimitPolicyReservation.window_descriptor == window_descriptor,
                LimitPolicyReservation.window_descriptor.is_(None),
            )
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
                func.coalesce(func.sum(LimitPolicyReservation.reserved_cost_micro_cents), 0),
            ).where(*filters)
        )
    ).one()
    return LimitPolicyReservationSummary(
        requests=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        cost_cents=int(row[4]),
        cost_micro_cents=int(row[5]),
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
                func.coalesce(func.sum(LimitPolicyReservation.reserved_cost_micro_cents), 0),
            ).where(*filters)
        )
    ).one()
    return LimitPolicyReservationSummary(
        requests=int(row[0]),
        prompt_tokens=int(row[1]),
        completion_tokens=int(row[2]),
        total_tokens=int(row[3]),
        cost_cents=int(row[4]),
        cost_micro_cents=int(row[5]),
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
    request_id: str | None,
    search: str | None,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
    limit: int | None,
    offset: int,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    filters = _usage_filters(
        org_id=org_id,
        since=since,
        until=until,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=request_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    if search:
        # autoescape escapes %/_ so a literal wildcard in the term matches verbatim.
        term = search.strip()
        filters.append(
            or_(
                UsageRecord.request_id.icontains(term, autoescape=True),
                UsageRecord.requested_model.icontains(term, autoescape=True),
                UsageRecord.provider_model.icontains(term, autoescape=True),
                UsageRecord.error_code.icontains(term, autoescape=True),
                ProviderCredential.name.icontains(term, autoescape=True),
                ProviderCredential.key_prefix.icontains(term, autoescape=True),
            )
        )
    query = (
        select(UsageRecord, ProviderCredential.name, ProviderCredential.key_prefix)
        .outerjoin(ProviderCredential, ProviderCredential.id == UsageRecord.provider_credential_id)
        .where(*filters)
        .order_by(UsageRecord.created_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)
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
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int, int]:
    filters = [
        LimitPolicyCommittedUsage.limit_policy_id == limit_policy_id,
    ]
    if limit_policy_rule_id is not None:
        filters.append(LimitPolicyCommittedUsage.limit_policy_rule_id == limit_policy_rule_id)
    if limit_policy_assignment_id is not None:
        filters.append(
            LimitPolicyCommittedUsage.limit_policy_assignment_id == limit_policy_assignment_id
        )
    if counter_key is not None:
        filters.append(LimitPolicyCommittedUsage.counter_key == counter_key)
    if counting_unit is not None:
        filters.append(LimitPolicyCommittedUsage.counting_unit == counting_unit)
    if window_descriptor is not None:
        filters.append(
            or_(
                LimitPolicyCommittedUsage.window_descriptor == window_descriptor,
                LimitPolicyCommittedUsage.window_descriptor.is_(None),
            )
        )
    if since is not None:
        filters.append(LimitPolicyCommittedUsage.created_at >= since)
    row = (
        await db.execute(
            select(
                func.count(LimitPolicyCommittedUsage.id),
                func.coalesce(func.sum(LimitPolicyCommittedUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LimitPolicyCommittedUsage.completion_tokens), 0),
                func.coalesce(func.sum(LimitPolicyCommittedUsage.cost_cents), 0),
                func.coalesce(func.sum(LimitPolicyCommittedUsage.cost_micro_cents), 0),
            ).where(*filters)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4])


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
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    filters = tuple(
        _usage_filters(
            org_id=org_id,
            since=since,
            until=until,
            team_id=team_id,
            provider_id=provider_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            model=model,
            request_id=None,
            allowed_team_ids=allowed_team_ids,
            allowed_project_ids=allowed_project_ids,
            allowed_virtual_key_ids=allowed_virtual_key_ids,
        )
    )
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
            None,
            *filters,
            db=db,
        ),
        by_project=await _breakdown(
            UsageRecord.project_id,
            None,
            *filters,
            db=db,
        ),
        by_access_policy=await _breakdown(
            UsageRecord.access_policy_id,
            Policy.name,
            *filters,
            join_model=Policy,
            join_on=Policy.id == UsageRecord.access_policy_id,
            db=db,
        ),
        by_virtual_key=await _breakdown(
            UsageRecord.virtual_key_id,
            None,
            *filters,
            db=db,
        ),
        recent_errors=await _recent_errors(*filters, db=db),
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
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> list[UsageTimeSeriesPoint]:
    filters = _usage_filters(
        org_id=org_id,
        since=since,
        until=until,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=None,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    bucket_expr = _bucket_expression(grain=grain, db=db)
    rows = (
        await db.execute(
            select(
                bucket_expr.label("bucket"),
                _logical_request_count_expression(),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (UsageRecord.is_final_attempt.is_(True))
                                & (UsageRecord.http_status < 400),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (UsageRecord.is_final_attempt.is_(True))
                                & (UsageRecord.http_status >= 400),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
                *_spend_classification_columns(),
                func.avg(UsageRecord.latency_ms),
                func.max(UsageRecord.created_at),
            )
            .where(*filters)
            .group_by(bucket_expr)
            .order_by(bucket_expr.asc())
        )
    ).all()
    return [
        UsageTimeSeriesPoint(
            bucket=_coerce_bucket_datetime(row[0]),
            **_row_to_totals(row[1:]).model_dump(),
        )
        for row in rows
    ]


async def get_usage_filter_options(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> UsageFilterOptions:
    filters = tuple(
        _usage_filters(
            org_id=org_id,
            since=since,
            until=until,
            team_id=team_id,
            provider_id=None,
            project_id=project_id,
            virtual_key_id=None,
            model=None,
            request_id=None,
            allowed_team_ids=allowed_team_ids,
            allowed_project_ids=allowed_project_ids,
            allowed_virtual_key_ids=allowed_virtual_key_ids,
        )
    )
    return UsageFilterOptions(
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
        by_team=await _breakdown(
            UsageRecord.team_id,
            None,
            *filters,
            db=db,
        ),
        by_project=await _breakdown(
            UsageRecord.project_id,
            None,
            *filters,
            db=db,
        ),
        by_virtual_key=await _breakdown(
            UsageRecord.virtual_key_id,
            None,
            *filters,
            db=db,
        ),
    )


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
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
    db: AsyncSession,
) -> SpendInsights:
    filters = _usage_filters(
        org_id=org_id,
        since=since,
        until=until,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=None,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
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
            allowed_team_ids=allowed_team_ids,
            allowed_project_ids=allowed_project_ids,
            allowed_virtual_key_ids=allowed_virtual_key_ids,
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
            Policy.name,
            *base_filters,
            join_model=Policy,
            join_on=Policy.id == UsageRecord.access_policy_id,
            db=db,
        ),
        recent_errors=await _recent_errors(*base_filters, db=db),
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
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
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
        rule_since = _limit_rule_window_start(
            interval_unit=rule.interval_unit,
            interval_count=rule.interval_count,
        )
        filters = [
            UsageRecord.org_id == org_id,
            _json_array_contains(UsageRecord.limit_policy_ids, rule.limit_policy_id, db=db),
            _json_array_contains(UsageRecord.limit_policy_rule_ids, rule.id, db=db),
        ]
        if rule_since is not None:
            filters.append(UsageRecord.created_at >= rule_since)
        window_descriptor = _limit_rule_window_descriptor(
            interval_unit=rule.interval_unit,
            interval_count=rule.interval_count,
        )
        filters.append(
            or_(
                UsageRecord.limit_window_descriptor == window_descriptor,
                UsageRecord.limit_window_descriptor.is_(None),
            )
        )
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
        _add_allowed_scope_filters(
            filters,
            allowed_team_ids=allowed_team_ids,
            allowed_project_ids=allowed_project_ids,
            allowed_virtual_key_ids=allowed_virtual_key_ids,
        )
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


def _limit_rule_window_descriptor(*, interval_unit: str, interval_count: int) -> str:
    if interval_unit == "lifetime":
        return f"{interval_unit}:{interval_count}:lifetime"
    return f"{interval_unit}:{interval_count}:rolling"


def _limit_rule_window_start(*, interval_unit: str, interval_count: int) -> datetime | None:
    now = datetime.now(UTC)
    if interval_unit == "hour":
        return now - timedelta(hours=interval_count)
    if interval_unit == "day":
        return now - timedelta(days=interval_count)
    if interval_unit == "week":
        return now - timedelta(weeks=interval_count)
    if interval_unit == "month":
        return subtract_months(now, interval_count)
    if interval_unit == "year":
        return subtract_months(now, 12 * interval_count)
    return None


def _usage_filters(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    provider_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    model: str | None,
    request_id: str | None,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
) -> list:
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
    if request_id:
        filters.append(UsageRecord.request_id == request_id)
    _add_allowed_scope_filters(
        filters,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    return filters


def _add_allowed_scope_filters(
    filters: list,
    *,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
) -> None:
    if (
        allowed_team_ids is None
        and allowed_project_ids is None
        and allowed_virtual_key_ids is None
    ):
        return
    scope_filters = []
    if allowed_team_ids:
        scope_filters.append(UsageRecord.team_id.in_(allowed_team_ids))
    if allowed_project_ids:
        scope_filters.append(UsageRecord.project_id.in_(allowed_project_ids))
    if allowed_virtual_key_ids:
        scope_filters.append(UsageRecord.virtual_key_id.in_(allowed_virtual_key_ids))
    filters.append(or_(*scope_filters) if scope_filters else UsageRecord.id.is_(None))


def _add_allowed_gateway_request_scope_filters(
    filters: list,
    *,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
) -> None:
    if (
        allowed_team_ids is None
        and allowed_project_ids is None
        and allowed_virtual_key_ids is None
    ):
        return
    scope_filters = []
    if allowed_team_ids:
        scope_filters.append(GatewayRequest.team_id.in_(allowed_team_ids))
    if allowed_project_ids:
        scope_filters.append(GatewayRequest.project_id.in_(allowed_project_ids))
    if allowed_virtual_key_ids:
        scope_filters.append(GatewayRequest.virtual_key_id.in_(allowed_virtual_key_ids))
    filters.append(or_(*scope_filters) if scope_filters else GatewayRequest.id.is_(None))


def _gateway_request_status_filter(status: str):
    denied_codes = {
        "invalid_virtual_key",
        "access_denied",
        "guardrail_denied",
        "guardrail_output_denied",
        "limit_exceeded",
        "request_validation_denied",
        "request_body_too_large",
    }
    denied_statuses = {400, 401, 403, 404, 413, 422, 429}
    if status == "pending":
        return GatewayRequest.completed_at.is_(None)
    if status == "succeeded":
        return (
            GatewayRequest.final_http_status.is_not(None)
            & (GatewayRequest.final_http_status >= 200)
            & (GatewayRequest.final_http_status < 400)
        )
    denied_filter = or_(
        GatewayRequest.final_error_code.in_(denied_codes),
        (
            GatewayRequest.final_http_status.in_(denied_statuses)
            & GatewayRequest.final_error_code.is_not(None)
            & (GatewayRequest.final_error_code != "provider_upstream_error")
            & (GatewayRequest.final_error_code != "provider_unavailable")
        ),
    )
    if status == "denied":
        return denied_filter
    if status == "failed":
        return (
            GatewayRequest.completed_at.is_not(None)
            & (
                (GatewayRequest.final_http_status.is_(None))
                | (GatewayRequest.final_http_status < 200)
                | (GatewayRequest.final_http_status >= 400)
            )
            & ~denied_filter
        )
    return GatewayRequest.id.is_not(None)


def _json_array_contains(column, value: UUID, *, db: AsyncSession):
    value_text = str(value)
    if db.bind and db.bind.dialect.name == "sqlite":
        json_each = func.json_each(column).table_valued("value")
        return select(1).select_from(json_each).where(json_each.c.value == value_text).exists()
    if db.bind and db.bind.dialect.name == "postgresql":
        return _json_array_contains_postgresql(column, value)
    return column.contains([value_text])


def _json_array_contains_postgresql(column, value: UUID):
    return cast(column, JSONB).contains([str(value)])


def _bucket_expression(*, grain: str, db: AsyncSession):
    dialect_name = db.bind.dialect.name if db.bind else ""
    if dialect_name == "sqlite":
        if grain == "hour":
            return func.strftime("%Y-%m-%d %H:00:00", UsageRecord.created_at)
        if grain == "week":
            weekday_offset = (cast(func.strftime("%w", UsageRecord.created_at), Integer) + 6) % 7
            return func.strftime(
                "%Y-%m-%d 00:00:00",
                func.date(
                    UsageRecord.created_at,
                    func.printf("-%d days", weekday_offset),
                ),
            )
        return func.strftime("%Y-%m-%d 00:00:00", UsageRecord.created_at)
    if grain == "hour":
        return func.date_trunc("hour", UsageRecord.created_at)
    if grain == "week":
        return func.date_trunc("week", UsageRecord.created_at)
    return func.date_trunc("day", UsageRecord.created_at)


def _coerce_bucket_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


async def _totals(*filters, db: AsyncSession) -> UsageSummaryTotals:
    row = (
        await db.execute(
            select(
                _logical_request_count_expression(),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (UsageRecord.is_final_attempt.is_(True))
                                & (UsageRecord.http_status < 400),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (UsageRecord.is_final_attempt.is_(True))
                                & (UsageRecord.http_status >= 400),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
                *_spend_classification_columns(),
                func.avg(UsageRecord.latency_ms),
                func.max(UsageRecord.created_at),
            ).where(*filters)
        )
    ).one()
    return _row_to_totals(row)


def _logical_request_count_expression():
    return func.count(func.distinct(func.coalesce(UsageRecord.gateway_request_id, UsageRecord.id)))


async def _breakdown(
    group_column,
    label_column=None,
    *filters,
    db: AsyncSession,
    join_model=None,
    join_on=None,
) -> list[UsageBreakdownRow]:
    label_column = label_column if label_column is not None else group_column
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
        *_spend_classification_columns(),
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
        confirmed_spend_cents=int(row[7]),
        estimated_spend_cents=int(row[8]),
        unknown_usage_count=int(row[9]),
        unknown_total_tokens=int(row[10]),
        average_latency_ms=None if row[11] is None else round(row[11]),
        last_request_at=row[12],
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
        confirmed_spend_cents=int(row[9]),
        estimated_spend_cents=int(row[10]),
        unknown_usage_count=int(row[11]),
        unknown_total_tokens=int(row[12]),
        average_latency_ms=None if row[13] is None else round(row[13]),
        last_request_at=None,
    )


async def _recent_errors(*filters, db: AsyncSession) -> list[UsageRecentError]:
    rows = (
        await db.scalars(
            select(UsageRecord)
            .where(*filters, UsageRecord.http_status >= 400)
            .order_by(UsageRecord.created_at.desc())
            .limit(5)
        )
    ).all()
    return [UsageRecentError.model_validate(record) for record in rows]


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
        confirmed_spend_cents=sum(
            record.cost_cents or 0
            for record in records
            if getattr(record, "usage_source", None) == "provider_reported"
            and record.cost_cents is not None
        ),
        estimated_spend_cents=sum(
            record.cost_cents or 0
            for record in records
            if getattr(record, "usage_source", None) == "estimated"
            and record.cost_cents is not None
        ),
        unknown_usage_count=sum(
            1
            for record in records
            if record.cost_cents is None
            or getattr(record, "usage_source", None) in (None, "unknown")
        ),
        unknown_total_tokens=sum(
            record.total_tokens or 0
            for record in records
            if record.cost_cents is None
            or getattr(record, "usage_source", None) in (None, "unknown")
        ),
        average_latency_ms=round(sum(latencies) / len(latencies)) if latencies else None,
    )


def _spend_classification_columns():
    unknown_condition = (
        (UsageRecord.cost_cents.is_(None))
        | (UsageRecord.usage_source.is_(None))
        | (UsageRecord.usage_source == "unknown")
    )
    return (
        func.coalesce(
            func.sum(
                case(
                    (
                        (UsageRecord.usage_source == "provider_reported")
                        & UsageRecord.cost_cents.is_not(None),
                        UsageRecord.cost_cents,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        (UsageRecord.usage_source == "estimated")
                        & UsageRecord.cost_cents.is_not(None),
                        UsageRecord.cost_cents,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(func.sum(case((unknown_condition, 1), else_=0)), 0),
        func.coalesce(
            func.sum(case((unknown_condition, UsageRecord.total_tokens), else_=0)),
            0,
        ),
    )
