from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_write_unit
from app.core.request_ids import current_request_id
from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import RecordActivityEvent
from app.modules.gateway import costing as gateway_costing
from app.modules.gateway import limits as gateway_limits
from app.modules.usage import facade as usage_facade
from app.modules.usage.accounting import UsageAccounting, unknown_usage
from app.modules.usage.schemas import RecordUsage

HTTP_TOO_MANY_REQUESTS = 429


class AccountingResolvedAccess(Protocol):
    org_id: UUID
    team_id: UUID | None
    project_id: UUID | None
    access_policy_id: UUID | None
    access_policy_route_id: UUID | None
    public_model_id: UUID | None
    route_candidate_id: UUID | None
    primary_route_candidate_id: UUID | None
    public_model_name: str | None
    routing_mode: str | None
    limit_policy_ids: list[UUID]
    limit_policies: list[Any]
    virtual_key_id: UUID
    pool_id: UUID
    provider_id: UUID
    provider_key_id: UUID | None
    requested_model: str
    provider_model: str
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None


def _ordered_policy_ids(limits: list[Any]) -> list[str]:
    seen: set[UUID] = set()
    policy_ids: list[str] = []
    for limit in limits:
        if limit.limit_policy_id is None or limit.limit_policy_id in seen:
            continue
        seen.add(limit.limit_policy_id)
        policy_ids.append(str(limit.limit_policy_id))
    return policy_ids


@sqlite_write_unit
async def record_proxy_request(
    *,
    resolved: AccountingResolvedAccess,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
    http_status: int,
    latency_ms: int,
    usage: UsageAccounting,
    error_code: str | None,
    db: AsyncSession,
    provider_credential_id: UUID | None = None,
    routing_attempt_index: int = 0,
    is_final_attempt: bool = True,
    fallback_from_candidate_id: UUID | None = None,
    fallback_trigger_reason: str | None = None,
    attempt_failure_reason: str | None = None,
    gateway_endpoint: str | None = None,
    count_toward_limits: bool | None = None,
) -> int | None:
    cost_cents = gateway_costing.calculate_cost_cents(resolved=resolved, usage=usage)
    cost_micro_cents = gateway_costing.calculate_cost_micro_cents(
        resolved=resolved,
        usage=usage,
    )
    limit_usage_context = await gateway_limits.build_committed_usage_context(
        resolved=resolved,
        gateway_endpoint=gateway_endpoint,
        db=db,
    )
    usage_record_id = await usage_facade.create_usage_record(
        payload=RecordUsage(
            org_id=resolved.org_id,
            team_id=resolved.team_id,
            project_id=resolved.project_id,
            access_policy_id=resolved.access_policy_id,
            access_policy_route_id=resolved.access_policy_route_id,
            gateway_request_id=gateway_request_id,
            route_attempt_id=route_attempt_id,
            public_model_id=resolved.public_model_id,
            route_candidate_id=resolved.route_candidate_id,
            limit_policy_ids=_ordered_policy_ids(limit_usage_context.matching_limits),
            limit_policy_rule_ids=[
                str(limit.limit_policy_rule_id)
                for limit in limit_usage_context.matching_limits
                if limit.limit_policy_rule_id is not None
            ],
            limit_policy_assignment_ids=[
                str(limit.limit_policy_assignment_id)
                for limit in limit_usage_context.matching_limits
                if limit.limit_policy_assignment_id is not None
            ],
            limit_counter_key=limit_usage_context.limit_counter_key,
            limit_counting_unit=limit_usage_context.limit_counting_unit,
            limit_window_descriptor=limit_usage_context.limit_window_descriptor,
            dimension_snapshot=limit_usage_context.dimension_snapshot,
            virtual_key_id=resolved.virtual_key_id,
            pool_id=resolved.pool_id,
            provider_id=resolved.provider_id,
            provider_credential_id=provider_credential_id or resolved.provider_key_id,
            request_id=current_request_id(),
            requested_model=resolved.requested_model,
            provider_model=resolved.provider_model,
            public_model_name=resolved.public_model_name,
            routing_mode=resolved.routing_mode,
            routing_attempt_index=routing_attempt_index,
            is_final_attempt=is_final_attempt,
            primary_route_candidate_id=resolved.primary_route_candidate_id,
            fallback_from_candidate_id=fallback_from_candidate_id,
            fallback_trigger_reason=fallback_trigger_reason,
            attempt_failure_reason=attempt_failure_reason,
            gateway_endpoint=gateway_endpoint,
            http_status=http_status,
            latency_ms=latency_ms,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_cents=cost_cents,
            cost_micro_cents=cost_micro_cents,
            usage_source=usage.usage_source,
            error_code=error_code,
        ),
        db=db,
    )
    should_count_toward_limits = (
        http_status < 400 if count_toward_limits is None else count_toward_limits
    )
    if should_count_toward_limits:
        await gateway_limits.record_committed_usage(
            resolved=resolved,
            usage_record_id=usage_record_id,
            usage=usage,
            cost_cents=cost_cents,
            cost_micro_cents=cost_micro_cents,
            dimension_subject=limit_usage_context.dimension_subject,
            dimension_snapshot=limit_usage_context.dimension_snapshot,
            matching_limits=limit_usage_context.matching_limits,
            db=db,
        )
        await db.commit()
    return cost_cents


async def record_limit_denial_side_effects(
    *,
    resolved: AccountingResolvedAccess,
    denial: gateway_limits.GatewayLimitDeniedError,
    gateway_request_id: UUID | None,
    route_attempt_id: UUID | None,
    db: AsyncSession,
) -> None:
    await record_proxy_request(
        resolved=resolved,
        gateway_request_id=gateway_request_id,
        route_attempt_id=denial.route_attempt_id or route_attempt_id,
        http_status=HTTP_TOO_MANY_REQUESTS,
        latency_ms=0,
        usage=unknown_usage(),
        error_code="limit_policy_denied",
        gateway_endpoint=denial.gateway_endpoint,
        db=db,
    )
    await record_proxy_activity(
        resolved=resolved,
        action="proxy.denied",
        message=denial.detail,
        severity="warning",
        metadata=denial.activity_metadata,
        gateway_request_id=gateway_request_id,
        db=db,
    )


@sqlite_write_unit
async def record_proxy_activity(
    *,
    resolved: AccountingResolvedAccess,
    action: str,
    message: str,
    severity: str,
    metadata: dict[str, Any],
    db: AsyncSession,
    gateway_request_id: UUID | None = None,
) -> None:
    await activity_facade.record_event_and_commit(
        payload=RecordActivityEvent(
            org_id=resolved.org_id,
            category="proxy",
            severity=severity,
            action=action,
            message=message,
            team_id=resolved.team_id,
            project_id=resolved.project_id,
            virtual_key_id=resolved.virtual_key_id,
            provider_id=resolved.provider_id,
            pool_id=resolved.pool_id,
            request_id=current_request_id(),
            gateway_request_id=gateway_request_id,
            metadata={
                **metadata,
                "requested_model": resolved.requested_model,
                "provider_model": resolved.provider_model,
            },
        ),
        db=db,
    )

