from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_write_unit
from app.core.request_ids import current_request_id
from app.modules.gateway import costing as gateway_costing
from app.modules.gateway_history import facade as gateway_history_facade
from app.modules.policies.dimensions import PolicyDimensionStage, to_dimension_snapshot
from app.modules.policies.runtime_limits import (
    RuntimeLimitEvaluationInput,
    evaluate_runtime_limits_readonly,
    limit_dimension_subject,
    limit_policy_window_descriptor,
    limit_rule_counter_identity,
    limit_rule_counter_key,
    limit_rule_counting_unit,
    matching_runtime_limits,
)
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.usage import facade as usage_facade
from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.schemas import (
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
)

ESTIMATED_LIMIT_TYPES = {
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tokens_per_request",
    "budget_cents",
}
REQUEST_LIMIT_TYPES = {"requests"}


class LimitResolvedAccess(Protocol):
    org_id: UUID
    team_id: UUID | None
    project_id: UUID | None
    public_model_id: UUID | None
    route_candidate_id: UUID | None
    public_model_name: str | None
    routing_mode: str | None
    model_offering_id: UUID
    limit_policy_ids: list[UUID]
    limit_policies: list[Any]
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    provider_key_id: UUID | None
    requested_model: str
    provider_model: str
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None


@dataclass(frozen=True)
class GatewayLimitDeniedError(Exception):
    detail: str
    activity_metadata: dict[str, Any]
    gateway_endpoint: str | None
    route_attempt_id: UUID | None


@dataclass(frozen=True)
class CommittedUsageContext:
    dimension_subject: dict[str, Any]
    dimension_snapshot: dict[str, Any]
    matching_limits: list[Any]
    limit_counter_key: str | None
    limit_counting_unit: str
    limit_window_descriptor: str | None


@dataclass(frozen=True, slots=True)
class PersistedLimitReference:
    limit_policy_id: UUID
    limit_policy_revision_id: UUID
    limit_policy_rule_id: UUID
    limit_policy_assignment_id: UUID


def persisted_limit_reference(limit: Any) -> PersistedLimitReference:
    if (
        limit.limit_policy_id is None
        or limit.limit_policy_revision_id is None
        or limit.limit_policy_rule_id is None
        or limit.limit_policy_assignment_id is None
    ):
        raise RuntimeError("persisted limit accounting requires resolved policy references")
    return PersistedLimitReference(
        limit_policy_id=limit.limit_policy_id,
        limit_policy_revision_id=limit.limit_policy_revision_id,
        limit_policy_rule_id=limit.limit_policy_rule_id,
        limit_policy_assignment_id=limit.limit_policy_assignment_id,
    )


@sqlite_write_unit
async def enforce_limit_policies(
    *,
    resolved: LimitResolvedAccess,
    estimated_input_tokens: int,
    requested_output_tokens: int | None,
    limit_types: set[str] | None = None,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
    gateway_endpoint: str | None = None,
    db: AsyncSession,
) -> list[UUID]:
    requested_total_tokens = estimated_input_tokens + (requested_output_tokens or 0)
    estimated_usage = UsageAccounting(
        prompt_tokens=estimated_input_tokens,
        completion_tokens=requested_output_tokens,
        total_tokens=requested_total_tokens if requested_output_tokens is not None else None,
        usage_source="estimated",
    )
    estimated_cost_cents = gateway_costing.calculate_cost_cents(
        resolved=resolved,
        usage=estimated_usage,
    )
    estimated_cost_micro_cents = gateway_costing.calculate_cost_micro_cents(
        resolved=resolved, usage=estimated_usage
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    dimension_subject = limit_dimension_subject(
        resolved=resolved,
        gateway_endpoint=gateway_endpoint,
    )
    matched_limits = await matching_runtime_limits(
        resolved=resolved,
        subject=dimension_subject,
        limit_types=limit_types,
        db=db,
    )
    for counter_identity in sorted(
        {
            await limit_rule_counter_identity(
                org_id=resolved.org_id,
                limit=limit,
                subject=dimension_subject,
                db=db,
            )
            for limit in matched_limits
        }
    ):
        await usage_facade.acquire_limit_counter_lock(identity=counter_identity, db=db)

    evaluation = await evaluate_runtime_limits_readonly(
        payload=RuntimeLimitEvaluationInput(
            resolved=resolved,
            estimated_input_tokens=estimated_input_tokens,
            requested_output_tokens=requested_output_tokens,
            estimated_cost_cents=estimated_cost_cents,
            estimated_cost_micro_cents=estimated_cost_micro_cents,
            gateway_endpoint=gateway_endpoint,
            limit_types=limit_types,
            matching_limits=matched_limits,
        ),
        db=db,
    )
    if evaluation.denial is not None:
        denial = evaluation.denial
        await raise_limit_denial(
            resolved=resolved,
            limit=denial.limit,
            detail=denial.message or "limit policy exceeded",
            reason=denial.reason_code or "limit_exceeded",
            current_usage=denial.current_usage,
            reserved_usage=denial.active_reserved_usage,
            attempted_usage=denial.attempted_usage,
            gateway_request_id=gateway_request_id,
            route_attempt_id=route_attempt_id,
            gateway_endpoint=gateway_endpoint,
            dimension_snapshot=evaluation.dimension_snapshot,
            db=db,
        )

    reservation_ids: list[UUID] = []
    for result in evaluation.results:
        limit = result.limit
        if limit.limit_type == "tokens_per_request":
            continue
        limit_reference = persisted_limit_reference(limit)
        reservation_id = await usage_facade.create_limit_policy_reservation(
            payload=RecordLimitPolicyReservation(
                org_id=resolved.org_id,
                limit_policy_id=limit_reference.limit_policy_id,
                limit_policy_revision_id=limit_reference.limit_policy_revision_id,
                limit_policy_rule_id=limit_reference.limit_policy_rule_id,
                limit_policy_assignment_id=limit_reference.limit_policy_assignment_id,
                virtual_key_id=resolved.virtual_key_id,
                request_id=current_request_id(),
                counter_key=result.counter_key,
                counting_unit=result.counting_unit,
                window_descriptor=result.window_descriptor,
                dimension_snapshot=evaluation.dimension_snapshot,
                reserved_prompt_tokens=estimated_input_tokens,
                reserved_completion_tokens=requested_output_tokens or 0,
                reserved_total_tokens=requested_total_tokens,
                reserved_cost_cents=estimated_cost_cents,
                reserved_cost_micro_cents=estimated_cost_micro_cents,
                expires_at=expires_at,
            ),
            db=db,
        )
        reservation_ids.append(reservation_id)
        await record_gateway_limit_decision(
            resolved=resolved,
            limit=limit,
            gateway_request_id=gateway_request_id,
            route_attempt_id=route_attempt_id,
            stage="limit_reservation",
            outcome="reserved",
            effective_action="allow",
            reason_code="limit_reserved",
            message=None,
            dimension_snapshot=evaluation.dimension_snapshot,
            metadata={
                "reservation_id": str(reservation_id),
                "gateway_endpoint": gateway_endpoint,
                "counting_unit": result.counting_unit,
                "reserved_prompt_tokens": estimated_input_tokens,
                "reserved_completion_tokens": requested_output_tokens or 0,
                "reserved_total_tokens": requested_total_tokens,
                "reserved_cost_cents": estimated_cost_cents,
                "reserved_cost_micro_cents": estimated_cost_micro_cents,
            },
            db=db,
        )
    await db.commit()
    return reservation_ids


@sqlite_write_unit
async def commit_reservations(
    *,
    reservation_ids: list[UUID],
    usage: UsageAccounting,
    cost_cents: int | None,
    cost_micro_cents: int | None,
    db: AsyncSession,
) -> None:
    await usage_facade.commit_limit_policy_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=cost_cents,
        cost_micro_cents=cost_micro_cents,
        db=db,
    )
    await db.commit()


@sqlite_write_unit
async def release_reservations(*, reservation_ids: list[UUID], db: AsyncSession) -> None:
    await usage_facade.release_limit_policy_reservations(reservation_ids=reservation_ids, db=db)
    await db.commit()


async def build_committed_usage_context(
    *,
    resolved: LimitResolvedAccess,
    gateway_endpoint: str | None,
    db: AsyncSession,
) -> CommittedUsageContext:
    dimension_subject = limit_dimension_subject(
        resolved=resolved,
        gateway_endpoint=gateway_endpoint,
    )
    matching_limits = await matching_runtime_limits(
        resolved=resolved,
        subject=dimension_subject,
        limit_types=None,
        db=db,
    )
    return CommittedUsageContext(
        dimension_subject=dimension_subject,
        dimension_snapshot=to_dimension_snapshot(
            dimension_subject,
            stage=PolicyDimensionStage.LIMIT_COMMIT,
        ),
        matching_limits=matching_limits,
        limit_counter_key=await _usage_limit_counter_key(
            limits=matching_limits,
            subject=dimension_subject,
            db=db,
        ),
        limit_counting_unit=await _usage_limit_counting_unit(
            org_id=resolved.org_id,
            limits=matching_limits,
            db=db,
        ),
        limit_window_descriptor=_usage_limit_window_descriptor(limits=matching_limits),
    )


async def record_committed_usage(
    *,
    resolved: LimitResolvedAccess,
    usage_record_id: UUID,
    usage: UsageAccounting,
    cost_cents: int | None,
    cost_micro_cents: int | None,
    dimension_subject: dict[str, Any],
    dimension_snapshot: dict[str, Any],
    matching_limits: list[Any],
    db: AsyncSession,
) -> None:
    for limit in matching_limits:
        limit_reference = persisted_limit_reference(limit)
        counter_key = await limit_rule_counter_key(
            limit=limit,
            subject=dimension_subject,
            db=db,
        )
        counting_unit = await limit_rule_counting_unit(
            org_id=resolved.org_id,
            limit=limit,
            db=db,
        )
        await usage_facade.create_limit_policy_committed_usage(
            payload=RecordLimitPolicyCommittedUsage(
                org_id=resolved.org_id,
                usage_record_id=usage_record_id,
                limit_policy_id=limit_reference.limit_policy_id,
                limit_policy_revision_id=limit_reference.limit_policy_revision_id,
                limit_policy_rule_id=limit_reference.limit_policy_rule_id,
                limit_policy_assignment_id=limit_reference.limit_policy_assignment_id,
                counter_key=counter_key,
                counting_unit=counting_unit,
                window_descriptor=limit_policy_window_descriptor(limit),
                dimension_snapshot=dimension_snapshot,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cost_cents=cost_cents,
                cost_micro_cents=cost_micro_cents,
            ),
            db=db,
        )


async def raise_limit_denial(
    *,
    resolved: LimitResolvedAccess,
    limit: Any,
    detail: str,
    reason: str,
    current_usage: int | None,
    reserved_usage: int | None,
    attempted_usage: int | None,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
    gateway_endpoint: str | None = None,
    dimension_snapshot: dict[str, Any] | None = None,
    db: AsyncSession,
) -> None:
    metadata = {
        "reason": reason,
        "limit_policy_id": str(limit.limit_policy_id),
        "limit_policy_name": limit.limit_policy_name,
        "limit_policy_rule_id": str(limit.limit_policy_rule_id),
        "limit_policy_rule_name": limit.name,
        "limit_policy_assignment_id": str(limit.limit_policy_assignment_id),
        "limit_policy_assignment_scope": "resolved",
        "limit_type": limit.limit_type,
        "current_usage": current_usage,
        "reserved_usage": reserved_usage,
        "attempted_usage": attempted_usage,
        "configured_limit": limit.limit_value,
        "interval_unit": limit.interval_unit,
        "interval_count": limit.interval_count,
    }
    await record_gateway_limit_decision(
        resolved=resolved,
        limit=limit,
        gateway_request_id=gateway_request_id,
        route_attempt_id=route_attempt_id,
        stage="limit_reservation",
        outcome="denied",
        effective_action="deny",
        reason_code=reason,
        message=detail,
        dimension_snapshot=dimension_snapshot,
        metadata={
            "gateway_endpoint": gateway_endpoint,
            "current_usage": current_usage,
            "reserved_usage": reserved_usage,
            "attempted_usage": attempted_usage,
        },
        db=db,
    )
    raise GatewayLimitDeniedError(
        detail=detail,
        activity_metadata=metadata,
        gateway_endpoint=gateway_endpoint,
        route_attempt_id=route_attempt_id,
    )


async def record_gateway_limit_decision(
    *,
    resolved: LimitResolvedAccess,
    limit: Any,
    gateway_request_id: UUID | None,
    route_attempt_id: UUID | None,
    stage: str,
    outcome: str,
    effective_action: str,
    reason_code: str,
    message: str | None,
    dimension_snapshot: dict[str, Any] | None = None,
    metadata: dict[str, Any],
    db: AsyncSession,
) -> None:
    if gateway_request_id is None:
        return
    assignment = await policy_kernel_repository.get_policy_assignment(
        assignment_id=limit.limit_policy_assignment_id,
        org_id=resolved.org_id,
        db=db,
    )
    await gateway_history_facade.create_gateway_policy_decision(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": gateway_request_id,
            "route_attempt_id": route_attempt_id,
            "decision_type": "limit",
            "stage": stage,
            "outcome": outcome,
            "effective_action": effective_action,
            "enforced": True,
            "policy_id": assignment.policy_id if assignment else None,
            "policy_revision_id": limit.limit_policy_revision_id,
            "assignment_id": limit.limit_policy_assignment_id,
            "assignment_mode": assignment.mode if assignment else None,
            "assignment_scope_type": assignment.scope_type if assignment else None,
            "assignment_team_id": assignment.team_id if assignment else None,
            "assignment_project_id": assignment.project_id if assignment else None,
            "assignment_virtual_key_id": assignment.virtual_key_id if assignment else None,
            "rule_id": limit.limit_policy_rule_id,
            "route_candidate_id": resolved.route_candidate_id,
            "reason_code": reason_code,
            "message": message,
            "dimension_snapshot": {
                **(dimension_snapshot or {}),
                "limit_type": limit.limit_type,
            },
            "metadata_": {
                **metadata,
                "limit_policy_id": str(limit.limit_policy_id),
                "limit_policy_name": limit.limit_policy_name,
                "limit_policy_rule_id": str(limit.limit_policy_rule_id),
                "limit_policy_rule_name": limit.name,
                "limit_policy_assignment_id": str(limit.limit_policy_assignment_id),
                "configured_limit": limit.limit_value,
                "interval_unit": limit.interval_unit,
                "interval_count": limit.interval_count,
            },
        },
        db=db,
    )


async def _usage_limit_counter_key(
    *,
    limits: list[Any],
    subject: dict[str, Any],
    db: AsyncSession,
) -> str | None:
    counter_keys = {
        counter_key
        for limit in limits
        if (
            counter_key := await limit_rule_counter_key(
                limit=limit,
                subject=subject,
                db=db,
            )
        )
        is not None
    }
    if len(counter_keys) == 1:
        return next(iter(counter_keys))
    return None


def _usage_limit_window_descriptor(*, limits: list[Any]) -> str | None:
    descriptors = {
        limit_policy_window_descriptor(limit)
        for limit in limits
        if limit.limit_type != "tokens_per_request"
    }
    if len(descriptors) == 1:
        return next(iter(descriptors))
    return None


async def _usage_limit_counting_unit(
    *,
    org_id: UUID,
    limits: list[Any],
    db: AsyncSession,
) -> str:
    counting_units = {
        await limit_rule_counting_unit(org_id=org_id, limit=limit, db=db)
        for limit in limits
        if limit.limit_type == "requests"
    }
    if counting_units == {"route_attempt"}:
        return "route_attempt"
    return "logical_request"

