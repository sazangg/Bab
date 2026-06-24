from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.keys.schemas import ResolvedAccess
from app.modules.policy_kernel.models import Policy
from app.modules.providers.internal.models import CredentialPool, Provider
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.internal import repository
from app.modules.usage.redaction import redact_trace_value
from app.modules.usage.schemas import (
    CreateGatewayRequest,
    FinalizeGatewayRequest,
    GatewayPolicyDecisionTrace,
    GatewayRequestResolvedSubject,
    GatewayRequestTraceListItem,
    GatewayRequestTraceListResponse,
    GatewayRequestTraceResponse,
    GatewayRequestTraceSummary,
    GatewayRouteAttemptTrace,
    GatewayTraceTimelineItem,
    GuardrailEventTrace,
    LimitPolicyReservationSummary,
    OrganizationUsageSummary,
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
    RecordUsage,
    SpendInsights,
    UsageBreakdownRow,
    UsageFilterOptions,
    UsageRecordResponse,
    UsageTimeSeriesPoint,
    VirtualKeyUsageSummary,
)
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.schemas import WorkspaceAllowedScopeIds, WorkspaceLabelMaps


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


async def attach_gateway_request_subject(
    *,
    gateway_request_id: UUID | None,
    subject: GatewayRequestResolvedSubject,
    db: AsyncSession,
) -> None:
    if gateway_request_id is None:
        return
    await repository.attach_gateway_request_subject(
        gateway_request_id=gateway_request_id,
        subject=subject,
        db=db,
    )
    await db.commit()


async def attach_gateway_request_resolution(
    *,
    gateway_request_id: UUID | None,
    resolved: ResolvedAccess,
    db: AsyncSession,
) -> None:
    if gateway_request_id is None:
        return
    await repository.attach_gateway_request_resolution(
        gateway_request_id=gateway_request_id,
        values={
            "org_id": resolved.org_id,
            "team_id": resolved.team_id,
            "project_id": resolved.project_id,
            "virtual_key_id": resolved.virtual_key_id,
            "public_model_id": resolved.public_model_id,
            "public_model_name": resolved.public_model_name,
            "routing_mode": resolved.routing_mode,
        },
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


async def list_gateway_requests(
    *,
    org_id: UUID,
    window: str,
    start_at: datetime | None,
    end_at: datetime | None,
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
    limit: int,
    offset: int,
    db: AsyncSession,
) -> GatewayRequestTraceListResponse:
    now = datetime.now(UTC)
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    requests = await repository.list_gateway_requests(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        provider_id=provider_id,
        public_model_name=public_model_name,
        requested_model=requested_model,
        request_id=request_id,
        status=status,
        fallback=fallback,
        error_code=error_code,
        search=search,
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        limit=limit,
        offset=offset,
        now=now,
        db=db,
    )
    has_more = len(requests) > limit
    page_requests = requests[:limit]
    workspace_labels = await _workspace_labels_for_gateway_requests(
        org_id=org_id,
        requests=page_requests,
        db=db,
    )
    items = [
        await _to_gateway_request_trace_list_item(
            request,
            workspace_labels=workspace_labels,
            db=db,
        )
        for request in page_requests
    ]
    return GatewayRequestTraceListResponse(
        items=items,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


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
    request_trace = GatewayRequestTraceSummary.model_validate(gateway_request)
    route_attempt_traces = [
        GatewayRouteAttemptTrace.model_validate(attempt).model_copy(
            update={
                "pricing_snapshot": redact_trace_value(attempt.pricing_snapshot),
                "capability_snapshot": redact_trace_value(attempt.capability_snapshot),
                "route_snapshot": redact_trace_value(attempt.route_snapshot),
            }
        )
        for attempt in attempts
    ]
    policy_decision_traces = [
        GatewayPolicyDecisionTrace.model_validate(decision).model_copy(
            update={
                "dimension_snapshot": redact_trace_value(decision.dimension_snapshot),
                "metadata": redact_trace_value(decision.metadata_),
            }
        )
        for decision in decisions
    ]
    guardrail_event_traces = [
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
            metadata=redact_trace_value(event.metadata_),
            created_at=event.created_at,
        )
        for event in events
    ]
    usage_record_traces = [
        record.model_copy(
            update={"dimension_snapshot": redact_trace_value(record.dimension_snapshot)}
        )
        for record in usage_records
    ]
    return GatewayRequestTraceResponse(
        request=request_trace,
        timeline=_build_gateway_trace_timeline(
            request=request_trace,
            route_attempts=route_attempt_traces,
            policy_decisions=policy_decision_traces,
            guardrail_events=guardrail_event_traces,
            usage_records=usage_record_traces,
        ),
        route_attempts=route_attempt_traces,
        policy_decisions=policy_decision_traces,
        guardrail_events=guardrail_event_traces,
        usage_records=usage_record_traces,
    )


async def _to_gateway_request_trace_list_item(
    request,
    *,
    workspace_labels: WorkspaceLabelMaps,
    db: AsyncSession,
) -> GatewayRequestTraceListItem:
    attempts = await repository.list_gateway_route_attempts(
        gateway_request_id=request.id,
        org_id=request.org_id,
        db=db,
    )
    final_attempt = next(
        (attempt for attempt in attempts if attempt.id == request.final_route_attempt_id),
        None,
    )
    final_provider = (
        await db.get(Provider, request.final_provider_id)
        if request.final_provider_id and final_attempt is None
        else None
    )
    final_pool = (
        await db.get(CredentialPool, request.final_credential_pool_id)
        if request.final_credential_pool_id and final_attempt is None
        else None
    )
    final_policy = (
        await db.get(Policy, request.final_access_policy_id)
        if request.final_access_policy_id and final_attempt is None
        else None
    )
    involved_provider_ids: list[UUID] = []
    involved_provider_names: list[str] = []
    seen_provider_ids: set[UUID] = set()
    for attempt in attempts:
        if attempt.provider_id is None or attempt.provider_id in seen_provider_ids:
            continue
        seen_provider_ids.add(attempt.provider_id)
        involved_provider_ids.append(attempt.provider_id)
        if attempt.provider_name:
            involved_provider_names.append(attempt.provider_name)
        else:
            provider = await db.get(Provider, attempt.provider_id)
            if provider is not None:
                involved_provider_names.append(provider.name)

    return GatewayRequestTraceListItem(
        id=request.id,
        org_id=request.org_id,
        team_id=request.team_id,
        project_id=request.project_id,
        virtual_key_id=request.virtual_key_id,
        request_id=request.request_id,
        gateway_endpoint=request.gateway_endpoint,
        requested_model=request.requested_model,
        public_model_name=request.public_model_name,
        routing_mode=request.routing_mode,
        final_http_status=request.final_http_status,
        final_provider_id=request.final_provider_id,
        final_provider_name=(
            final_attempt.provider_name
            if final_attempt is not None
            else final_provider.name
            if final_provider is not None
            else None
        ),
        final_credential_pool_id=request.final_credential_pool_id,
        final_credential_pool_name=(
            final_attempt.credential_pool_name
            if final_attempt is not None
            else final_pool.name
            if final_pool is not None
            else None
        ),
        final_provider_model=request.final_provider_model,
        final_access_policy_id=request.final_access_policy_id,
        final_access_policy_name=(
            (final_attempt.route_snapshot or {}).get("access_policy_name")
            if final_attempt is not None
            else final_policy.name
            if final_policy is not None
            else None
        ),
        team_name=workspace_labels.teams.get(request.team_id) if request.team_id else None,
        project_name=(
            workspace_labels.projects.get(request.project_id) if request.project_id else None
        ),
        virtual_key_name=(
            workspace_labels.virtual_keys.get(request.virtual_key_id)
            if request.virtual_key_id
            else None
        ),
        involved_provider_ids=involved_provider_ids,
        involved_provider_names=involved_provider_names,
        attempt_count=request.attempt_count,
        fallback_attempted=request.fallback_attempted,
        final_error_code=request.final_error_code,
        started_at=request.started_at,
        completed_at=request.completed_at,
        trace_expires_at=request.trace_expires_at,
        outcome=_gateway_request_outcome(request),
        duration_ms=_gateway_request_duration_ms(request),
    )


def _gateway_request_duration_ms(request) -> int | None:
    if request.completed_at is None:
        return None
    completed_at = _timeline_sort_timestamp(request.completed_at)
    started_at = _timeline_sort_timestamp(request.started_at)
    return max(0, round((completed_at - started_at).total_seconds() * 1000))


def _gateway_request_outcome(request) -> str:
    if request.completed_at is None:
        return "pending"
    if (
        request.final_http_status is not None
        and 200 <= request.final_http_status < 400
    ):
        return "succeeded"
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
    if request.final_error_code in denied_codes:
        return "denied"
    if (
        request.final_http_status in denied_statuses
        and request.final_error_code is not None
        and request.final_error_code not in {"provider_upstream_error", "provider_unavailable"}
    ):
        return "denied"
    return "failed"


def _build_gateway_trace_timeline(
    *,
    request: GatewayRequestTraceSummary,
    route_attempts: list[GatewayRouteAttemptTrace],
    policy_decisions: list[GatewayPolicyDecisionTrace],
    guardrail_events: list[GuardrailEventTrace],
    usage_records: list[UsageRecordResponse],
) -> list[GatewayTraceTimelineItem]:
    items: list[tuple[int, int, GatewayTraceTimelineItem]] = [
        (
            0,
            0,
            GatewayTraceTimelineItem(
                timestamp=request.started_at,
                kind="request",
                title="Request started",
                status=_gateway_request_outcome(request),
                severity="info",
                summary=request.requested_model,
                metadata={
                    "gateway_endpoint": request.gateway_endpoint,
                    "request_id": request.request_id,
                    "public_model_name": request.public_model_name,
                },
            ),
        )
    ]
    for attempt in route_attempts:
        items.append(
            (
                2,
                attempt.attempt_index,
                GatewayTraceTimelineItem(
                    timestamp=attempt.started_at,
                    kind="route_attempt",
                    title="Route attempt started",
                    status=attempt.status,
                    route_attempt_id=attempt.id,
                    severity="info",
                    summary=_route_attempt_summary(attempt),
                    metadata={
                        "attempt_index": attempt.attempt_index,
                        "provider_name": attempt.provider_name,
                        "credential_pool_name": attempt.credential_pool_name,
                        "provider_model": attempt.provider_model,
                    },
                ),
            )
        )
        if attempt.completed_at is not None:
            items.append(
                (
                    2,
                    attempt.attempt_index,
                    GatewayTraceTimelineItem(
                        timestamp=attempt.completed_at,
                        kind="route_attempt",
                        title="Route attempt completed",
                        status=attempt.status,
                        route_attempt_id=attempt.id,
                        severity=_route_attempt_severity(attempt.status),
                        summary=attempt.error_code or attempt.failure_reason,
                        metadata={
                            "attempt_index": attempt.attempt_index,
                            "http_status": attempt.http_status,
                            "latency_ms": attempt.latency_ms,
                        },
                    ),
                )
            )
    for decision in policy_decisions:
        items.append(
            (
                1,
                0,
                GatewayTraceTimelineItem(
                    timestamp=decision.created_at,
                    kind="policy_decision",
                    title=_policy_decision_title(decision),
                    status=decision.outcome,
                    stage=decision.stage,
                    route_attempt_id=decision.route_attempt_id,
                    policy_decision_id=decision.id,
                    severity=_policy_decision_severity(decision.outcome),
                    summary=decision.reason_code or decision.message,
                    metadata=decision.metadata,
                ),
            )
        )
    for event in guardrail_events:
        items.append(
            (
                3,
                0,
                GatewayTraceTimelineItem(
                    timestamp=event.created_at,
                    kind="guardrail_event",
                    title="Guardrail event",
                    status=event.decision,
                    stage=event.phase,
                    route_attempt_id=event.route_attempt_id,
                    guardrail_event_id=event.id,
                    severity=_guardrail_event_severity(event.decision),
                    summary=event.reason,
                    metadata=event.metadata,
                ),
            )
        )
    for record in usage_records:
        items.append(
            (
                4,
                record.routing_attempt_index,
                GatewayTraceTimelineItem(
                    timestamp=record.created_at,
                    kind="usage_record",
                    title="Usage recorded",
                    status=str(record.http_status),
                    usage_record_id=record.id,
                    severity="error" if record.error_code else "success",
                    summary=record.error_code or record.usage_source,
                    metadata={
                        "provider_model": record.provider_model,
                        "total_tokens": record.total_tokens,
                        "cost_cents": record.cost_cents,
                    },
                ),
            )
        )
    return [
        item
        for _kind_order, _attempt_index, item in sorted(
            items,
            key=lambda item: (_timeline_sort_timestamp(item[2].timestamp), item[0], item[1]),
        )
    ]


def _timeline_sort_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _route_attempt_summary(attempt: GatewayRouteAttemptTrace) -> str | None:
    parts = [part for part in (attempt.provider_name, attempt.provider_model) if part]
    return " / ".join(parts) if parts else None


def _route_attempt_severity(status: str) -> str:
    if status == "succeeded":
        return "success"
    if status == "failed":
        return "error"
    if status == "blocked":
        return "warning"
    return "info"


def _policy_decision_title(decision: GatewayPolicyDecisionTrace) -> str:
    return f"{decision.decision_type.replace('_', ' ').title()} decision"


def _policy_decision_severity(outcome: str) -> str:
    if outcome == "denied":
        return "error"
    if outcome == "would_deny":
        return "warning"
    if outcome in {"allowed", "reserved", "committed", "selected"}:
        return "success"
    return "info"


def _guardrail_event_severity(decision: str) -> str:
    if decision == "blocked":
        return "error"
    if decision == "would_block":
        return "warning"
    return "info"


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
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
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
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
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
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    summary = await repository.get_organization_usage_summary(
        org_id=org_id,
        window=window,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        db=db,
    )
    return await _enrich_usage_workspace_breakdowns(org_id=org_id, summary=summary, db=db)


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
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
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
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
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
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
    options = await repository.get_usage_filter_options(
        org_id=org_id,
        since=start_at or window_start(window),
        until=end_at,
        team_id=team_id,
        project_id=project_id,
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
        db=db,
    )
    labels = await _workspace_labels_for_breakdowns(
        org_id=org_id,
        team_rows=options.by_team,
        project_rows=options.by_project,
        virtual_key_rows=options.by_virtual_key,
        db=db,
    )
    return options.model_copy(
        update={
            "by_team": _apply_labels(options.by_team, labels.teams),
            "by_project": _apply_labels(options.by_project, labels.projects),
            "by_virtual_key": _apply_labels(options.by_virtual_key, labels.virtual_keys),
        }
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
    allowed_scope = await _expand_allowed_scope_ids(
        org_id=org_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )
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
        allowed_team_ids=allowed_scope.team_ids if allowed_scope is not None else None,
        allowed_project_ids=allowed_scope.project_ids if allowed_scope is not None else None,
        allowed_virtual_key_ids=(
            allowed_scope.virtual_key_ids if allowed_scope is not None else None
        ),
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


async def _expand_allowed_scope_ids(
    *,
    org_id: UUID,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    db: AsyncSession,
) -> WorkspaceAllowedScopeIds | None:
    return await workspace_facade.expand_allowed_scope_ids(
        scope=Scope(org_id=org_id),
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )


async def _workspace_labels_for_gateway_requests(
    *,
    org_id: UUID,
    requests: list,
    db: AsyncSession,
) -> WorkspaceLabelMaps:
    return await workspace_facade.get_workspace_label_maps(
        scope=Scope(org_id=org_id),
        team_ids={request.team_id for request in requests if request.team_id is not None},
        project_ids={
            request.project_id for request in requests if request.project_id is not None
        },
        virtual_key_ids={
            request.virtual_key_id
            for request in requests
            if request.virtual_key_id is not None
        },
        db=db,
    )


async def _enrich_usage_workspace_breakdowns(
    *,
    org_id: UUID,
    summary: OrganizationUsageSummary,
    db: AsyncSession,
) -> OrganizationUsageSummary:
    labels = await _workspace_labels_for_breakdowns(
        org_id=org_id,
        team_rows=summary.by_team,
        project_rows=summary.by_project,
        virtual_key_rows=summary.by_virtual_key,
        db=db,
    )
    return summary.model_copy(
        update={
            "by_team": _apply_labels(summary.by_team, labels.teams),
            "by_project": _apply_labels(summary.by_project, labels.projects),
            "by_virtual_key": _apply_labels(summary.by_virtual_key, labels.virtual_keys),
        }
    )


async def _workspace_labels_for_breakdowns(
    *,
    org_id: UUID,
    team_rows: list[UsageBreakdownRow],
    project_rows: list[UsageBreakdownRow],
    virtual_key_rows: list[UsageBreakdownRow],
    db: AsyncSession,
) -> WorkspaceLabelMaps:
    return await workspace_facade.get_workspace_label_maps(
        scope=Scope(org_id=org_id),
        team_ids=_breakdown_ids(team_rows),
        project_ids=_breakdown_ids(project_rows),
        virtual_key_ids=_breakdown_ids(virtual_key_rows),
        db=db,
    )


def _breakdown_ids(rows: list[UsageBreakdownRow]) -> set[UUID]:
    ids: set[UUID] = set()
    for row in rows:
        try:
            ids.add(UUID(row.id))
        except ValueError:
            continue
    return ids


def _apply_labels(
    rows: list[UsageBreakdownRow],
    labels: dict[UUID, str],
) -> list[UsageBreakdownRow]:
    enriched: list[UsageBreakdownRow] = []
    for row in rows:
        try:
            row_id = UUID(row.id)
        except ValueError:
            enriched.append(row)
            continue
        enriched.append(row.model_copy(update={"label": labels.get(row_id, row.label)}))
    return enriched


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
