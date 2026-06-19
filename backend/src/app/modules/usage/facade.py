from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.internal import repository
from app.modules.usage.schemas import (
    CreateGatewayRequest,
    FinalizeGatewayRequest,
    GatewayPolicyDecisionTrace,
    GatewayRequestTraceResponse,
    GatewayRequestTraceSummary,
    GatewayRouteAttemptTrace,
    GuardrailEventTrace,
    LimitPolicyReservationSummary,
    OrganizationUsageSummary,
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
    RecordUsage,
    SpendInsights,
    UsageFilterOptions,
    UsageRecordResponse,
    UsageTimeSeriesPoint,
    VirtualKeyUsageSummary,
)


async def record_usage(*, payload: RecordUsage, db: AsyncSession) -> None:
    usage_record = await repository.create_usage_record(payload=payload, db=db)
    policy_ids = payload.limit_policy_ids or []
    rule_ids = payload.limit_policy_rule_ids or []
    assignment_ids = payload.limit_policy_assignment_ids or []
    for index, policy_id in enumerate(policy_ids):
        await repository.create_limit_policy_committed_usage(
            payload=RecordLimitPolicyCommittedUsage(
                org_id=payload.org_id,
                usage_record_id=usage_record.id,
                limit_policy_id=UUID(policy_id),
                limit_policy_rule_id=UUID(rule_ids[index]) if index < len(rule_ids) else None,
                limit_policy_assignment_id=(
                    UUID(assignment_ids[index]) if index < len(assignment_ids) else None
                ),
                counter_key=payload.limit_counter_key,
                counting_unit=payload.limit_counting_unit,
                window_descriptor=payload.limit_window_descriptor,
                dimension_snapshot=payload.dimension_snapshot,
                prompt_tokens=payload.prompt_tokens,
                completion_tokens=payload.completion_tokens,
                total_tokens=payload.total_tokens,
                cost_cents=payload.cost_cents,
                cost_micro_cents=payload.cost_micro_cents,
            ),
            db=db,
        )
    await db.commit()


async def create_usage_record(*, payload: RecordUsage, db: AsyncSession) -> UUID:
    usage_record = await repository.create_usage_record(payload=payload, db=db)
    await db.commit()
    return usage_record.id


async def create_limit_policy_committed_usage(
    *, payload: RecordLimitPolicyCommittedUsage, db: AsyncSession
) -> UUID:
    committed_usage = await repository.create_limit_policy_committed_usage(
        payload=payload,
        db=db,
    )
    return committed_usage.id


async def create_gateway_request(
    *,
    payload: CreateGatewayRequest,
    db: AsyncSession,
) -> UUID:
    gateway_request = await repository.create_gateway_request(payload=payload, db=db)
    await db.commit()
    return gateway_request.id


async def finalize_gateway_request(
    *,
    gateway_request_id: UUID,
    payload: FinalizeGatewayRequest,
    db: AsyncSession,
) -> None:
    await repository.finalize_gateway_request(
        gateway_request_id=gateway_request_id,
        payload=payload,
        db=db,
    )
    await db.commit()


async def create_gateway_route_attempt(*, values: dict, db: AsyncSession) -> UUID:
    route_attempt = await repository.create_gateway_route_attempt(values=values, db=db)
    await db.commit()
    return route_attempt.id


async def update_gateway_route_attempt(
    *,
    route_attempt_id: UUID,
    values: dict,
    db: AsyncSession,
) -> None:
    await repository.update_gateway_route_attempt(
        route_attempt_id=route_attempt_id,
        values=values,
        db=db,
    )
    await db.commit()


async def create_gateway_policy_decision(*, values: dict, db: AsyncSession) -> UUID:
    decision = await repository.create_gateway_policy_decision(values=values, db=db)
    await db.commit()
    return decision.id


async def get_gateway_request_trace(
    *,
    org_id: UUID,
    gateway_request_id: UUID,
    db: AsyncSession,
) -> GatewayRequestTraceResponse | None:
    gateway_request = await repository.get_gateway_request(
        gateway_request_id=gateway_request_id,
        org_id=org_id,
        db=db,
    )
    now = datetime.now(UTC)
    if gateway_request is None or gateway_request.trace_expires_at <= now:
        return None
    attempts = await repository.list_gateway_route_attempts(
        gateway_request_id=gateway_request_id,
        org_id=org_id,
        db=db,
    )
    decisions = await repository.list_gateway_policy_decisions(
        gateway_request_id=gateway_request_id,
        org_id=org_id,
        db=db,
    )
    events = await guardrails_repository.list_events_for_gateway_request(
        org_id=org_id,
        gateway_request_id=gateway_request_id,
        db=db,
    )
    usage_records = await repository.list_usage_records_for_gateway_request(
        gateway_request_id=gateway_request_id,
        org_id=org_id,
        db=db,
    )
    return GatewayRequestTraceResponse(
        request=GatewayRequestTraceSummary.model_validate(gateway_request),
        route_attempts=[GatewayRouteAttemptTrace.model_validate(attempt) for attempt in attempts],
        policy_decisions=[
            GatewayPolicyDecisionTrace.model_validate(decision) for decision in decisions
        ],
        guardrail_events=[
            GuardrailEventTrace(
                id=event.id,
                org_id=event.org_id,
                policy_id=event.policy_id,
                policy_revision_id=event.policy_revision_id,
                rule_id=event.rule_id,
                decision=event.decision,
                phase=event.phase,
                reason=event.reason,
                team_id=event.team_id,
                project_id=event.project_id,
                virtual_key_id=event.virtual_key_id,
                provider_id=event.provider_id,
                pool_id=event.pool_id,
                request_id=event.request_id,
                gateway_request_id=event.gateway_request_id,
                route_attempt_id=event.route_attempt_id,
                requested_model=event.requested_model,
                provider_model=event.provider_model,
                metadata=event.metadata_,
                created_at=event.created_at,
            )
            for event in events
        ],
        usage_records=usage_records,
    )


async def acquire_limit_scope_lock(*, assignment_id: UUID, db: AsyncSession) -> None:
    """Serialize concurrent limit enforcement for one policy assignment (Postgres
    advisory xact lock; a no-op on SQLite, which serializes writers anyway)."""
    await repository.acquire_limit_scope_lock(assignment_id=assignment_id, db=db)


async def acquire_limit_counter_lock(*, identity: str, db: AsyncSession) -> None:
    """Serialize concurrent limit enforcement for one resolved counter identity."""
    await repository.acquire_limit_counter_lock(identity=identity, db=db)


async def create_limit_policy_reservation(
    *,
    payload: RecordLimitPolicyReservation,
    db: AsyncSession,
) -> UUID:
    reservation = await repository.create_limit_policy_reservation(payload=payload, db=db)
    return reservation.id


async def summarize_active_limit_policy_reservations(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None = None,
    limit_policy_assignment_id: UUID | None = None,
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    return await repository.summarize_active_limit_policy_reservations(
        limit_policy_id=limit_policy_id,
        limit_policy_rule_id=limit_policy_rule_id,
        limit_policy_assignment_id=limit_policy_assignment_id,
        counter_key=counter_key,
        counting_unit=counting_unit,
        window_descriptor=window_descriptor,
        since=since,
        now=now,
        db=db,
    )


async def summarize_active_virtual_key_reservations(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    now: datetime,
    db: AsyncSession,
) -> LimitPolicyReservationSummary:
    return await repository.summarize_active_virtual_key_reservations(
        virtual_key_id=virtual_key_id,
        since=since,
        now=now,
        db=db,
    )


async def commit_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    usage: UsageAccounting,
    cost_cents: int | None,
    db: AsyncSession,
) -> None:
    await repository.commit_limit_policy_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=cost_cents,
        db=db,
    )
    await db.commit()


async def release_limit_policy_reservations(
    *,
    reservation_ids: list[UUID],
    db: AsyncSession,
) -> None:
    await repository.release_limit_policy_reservations(reservation_ids=reservation_ids, db=db)
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
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    request_id: str | None = None,
    search: str | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    limit: int | None = 100,
    offset: int = 0,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    records = await repository.list_usage_records(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=request_id,
        search=search,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        limit=limit,
        offset=offset,
        db=db,
    )
    return records


async def summarize_limit_policy_usage(
    *,
    limit_policy_id: UUID,
    limit_policy_rule_id: UUID | None = None,
    limit_policy_assignment_id: UUID | None = None,
    counter_key: str | None = None,
    counting_unit: str | None = None,
    window_descriptor: str | None = None,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int, int]:
    return await repository.summarize_limit_policy_usage(
        limit_policy_id=limit_policy_id,
        limit_policy_rule_id=limit_policy_rule_id,
        limit_policy_assignment_id=limit_policy_assignment_id,
        counter_key=counter_key,
        counting_unit=counting_unit,
        window_descriptor=window_descriptor,
        since=since,
        db=db,
    )


async def summarize_virtual_key_usage(
    *,
    virtual_key_id: UUID,
    since: datetime | None,
    db: AsyncSession,
) -> tuple[int, int, int, int]:
    return await repository.summarize_virtual_key_usage(
        virtual_key_id=virtual_key_id,
        since=since,
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
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
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
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
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
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
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
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )


async def get_usage_filter_options(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> UsageFilterOptions:
    return await repository.get_usage_filter_options(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        project_id=project_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )


async def get_spend_insights(
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
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> SpendInsights:
    return await repository.get_spend_insights(
        org_id=org_id,
        window=window,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
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


def limit_policy_window_start(window: str) -> datetime | None:
    now = datetime.now(UTC)
    if window == "daily":
        return now - timedelta(days=1)
    if window == "weekly":
        return now - timedelta(days=7)
    if window == "monthly":
        return now - timedelta(days=30)
    return None
