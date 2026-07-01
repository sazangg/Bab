from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.schemas import ResolvedLimitPolicy
from app.modules.policies.dimensions import (
    ATTEMPT_SCOPED_DIMENSIONS,
    PolicyDimensionStage,
    evaluate_matcher,
    to_dimension_snapshot,
)
from app.modules.policies.internal import repository as policies_repository
from app.modules.usage import facade as usage_facade
from app.modules.usage.accounting import subtract_months
from app.modules.usage.schemas import LimitPolicyReservationSummary


@dataclass(frozen=True, slots=True)
class RuntimeLimitEvaluationInput:
    resolved: Any
    estimated_input_tokens: int
    requested_output_tokens: int | None
    estimated_cost_cents: int | None
    estimated_cost_micro_cents: int | None
    gateway_endpoint: str | None = None
    limit_types: set[str] | None = None
    matching_limits: list[ResolvedLimitPolicy] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeLimitResult:
    limit: ResolvedLimitPolicy
    counter_key: str | None
    counting_unit: str
    window_descriptor: str
    current_usage: int | None
    active_reserved_usage: int | None
    attempted_usage: int | None
    would_deny: bool
    reason_code: str | None
    message: str | None


@dataclass(frozen=True, slots=True)
class RuntimeLimitEvaluation:
    dimension_subject: dict[str, Any]
    dimension_snapshot: dict[str, Any]
    results: list[RuntimeLimitResult]

    @property
    def matched_limits(self) -> list[ResolvedLimitPolicy]:
        return [result.limit for result in self.results]

    @property
    def denial(self) -> RuntimeLimitResult | None:
        return next((result for result in self.results if result.would_deny), None)


async def evaluate_runtime_limits_readonly(
    *,
    payload: RuntimeLimitEvaluationInput,
    db: AsyncSession,
) -> RuntimeLimitEvaluation:
    resolved = payload.resolved
    requested_output_tokens = payload.requested_output_tokens
    requested_total_tokens = payload.estimated_input_tokens + (requested_output_tokens or 0)
    dimension_subject = limit_dimension_subject(
        resolved=resolved,
        gateway_endpoint=payload.gateway_endpoint,
    )
    matched_limits = payload.matching_limits
    if matched_limits is None:
        matched_limits = await matching_runtime_limits(
            resolved=resolved,
            subject=dimension_subject,
            limit_types=payload.limit_types,
            db=db,
        )
    results: list[RuntimeLimitResult] = []
    for limit in matched_limits:
        static_result = _static_limit_result(
            limit=limit,
            estimated_input_tokens=payload.estimated_input_tokens,
            requested_output_tokens=requested_output_tokens,
            requested_total_tokens=requested_total_tokens,
        )
        if static_result is not None:
            results.append(static_result)
            continue

        since = limit_policy_window_start(limit.interval_unit, limit.interval_count)
        window_descriptor = limit_policy_window_descriptor(limit)
        counter_key = await limit_rule_counter_key(limit=limit, subject=dimension_subject, db=db)
        counting_unit = await limit_rule_counting_unit(
            org_id=resolved.org_id,
            limit=limit,
            db=db,
        )
        if _limit_counter_starts_at_zero(limit):
            results.append(
                _usage_limit_result(
                    limit=limit,
                    counter_key=counter_key,
                    counting_unit=counting_unit,
                    window_descriptor=window_descriptor,
                    request_count=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_cents=0,
                    cost_micro_cents=0,
                    reservations=LimitPolicyReservationSummary(),
                    estimated_input_tokens=payload.estimated_input_tokens,
                    requested_output_tokens=requested_output_tokens,
                    requested_total_tokens=requested_total_tokens,
                    estimated_cost_cents=payload.estimated_cost_cents,
                    estimated_cost_micro_cents=payload.estimated_cost_micro_cents,
                )
            )
            continue
        (
            request_count,
            prompt_tokens,
            completion_tokens,
            cost_cents,
            cost_micro_cents,
        ) = await usage_facade.summarize_limit_policy_usage(
            limit_policy_id=limit.limit_policy_id,
            limit_policy_rule_id=limit.limit_policy_rule_id,
            limit_policy_assignment_id=limit.limit_policy_assignment_id,
            counter_key=counter_key,
            counting_unit=counting_unit,
            window_descriptor=window_descriptor,
            since=since,
            db=db,
        )
        reservations = await usage_facade.summarize_active_limit_policy_reservations(
            limit_policy_id=limit.limit_policy_id,
            limit_policy_rule_id=limit.limit_policy_rule_id,
            limit_policy_assignment_id=limit.limit_policy_assignment_id,
            counter_key=counter_key,
            counting_unit=counting_unit,
            window_descriptor=window_descriptor,
            since=since,
            now=datetime.now(UTC),
            db=db,
        )
        results.append(
            _usage_limit_result(
                limit=limit,
                counter_key=counter_key,
                counting_unit=counting_unit,
                window_descriptor=window_descriptor,
                request_count=request_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_cents=cost_cents,
                cost_micro_cents=cost_micro_cents,
                reservations=reservations,
                estimated_input_tokens=payload.estimated_input_tokens,
                requested_output_tokens=requested_output_tokens,
                requested_total_tokens=requested_total_tokens,
                estimated_cost_cents=payload.estimated_cost_cents,
                estimated_cost_micro_cents=payload.estimated_cost_micro_cents,
            )
        )
    return RuntimeLimitEvaluation(
        dimension_subject=dimension_subject,
        dimension_snapshot=to_dimension_snapshot(
            dimension_subject,
            stage=PolicyDimensionStage.LIMIT_RESERVATION,
        ),
        results=results,
    )


async def matching_runtime_limits(
    *,
    resolved: Any,
    subject: dict[str, Any],
    limit_types: set[str] | None,
    db: AsyncSession,
) -> list[ResolvedLimitPolicy]:
    return [
        limit
        for limit in resolved.limit_policies
        if (limit_types is None or limit.limit_type in limit_types)
        and await limit_rule_matches_runtime_subject(limit=limit, subject=subject, db=db)
    ]


def _static_limit_result(
    *,
    limit: ResolvedLimitPolicy,
    estimated_input_tokens: int,
    requested_output_tokens: int | None,
    requested_total_tokens: int,
) -> RuntimeLimitResult | None:
    if limit.limit_type == "input_tokens" and estimated_input_tokens > limit.limit_value:
        return _denied_result(
            limit=limit,
            reason_code="input_token_limit",
            message="limit policy input token limit exceeded",
            current_usage=estimated_input_tokens,
            active_reserved_usage=0,
            attempted_usage=estimated_input_tokens,
        )
    if (
        limit.limit_type == "output_tokens"
        and requested_output_tokens is not None
        and requested_output_tokens > limit.limit_value
    ):
        return _denied_result(
            limit=limit,
            reason_code="output_token_limit",
            message="limit policy output token limit exceeded",
            current_usage=requested_output_tokens,
            active_reserved_usage=0,
            attempted_usage=requested_output_tokens,
        )
    if limit.limit_type == "tokens_per_request" and requested_total_tokens > limit.limit_value:
        return _denied_result(
            limit=limit,
            reason_code="request_token_limit",
            message="limit policy request token limit exceeded",
            current_usage=requested_total_tokens,
            active_reserved_usage=0,
            attempted_usage=requested_total_tokens,
        )
    if limit.limit_type == "tokens_per_request":
        return RuntimeLimitResult(
            limit=limit,
            counter_key=None,
            counting_unit="logical_request",
            window_descriptor=limit_policy_window_descriptor(limit),
            current_usage=requested_total_tokens,
            active_reserved_usage=0,
            attempted_usage=requested_total_tokens,
            would_deny=False,
            reason_code=None,
            message=None,
        )
    return None


def _usage_limit_result(
    *,
    limit: ResolvedLimitPolicy,
    counter_key: str | None,
    counting_unit: str,
    window_descriptor: str,
    request_count: int,
    prompt_tokens: int,
    completion_tokens: int,
    cost_cents: int,
    cost_micro_cents: int,
    reservations: LimitPolicyReservationSummary,
    estimated_input_tokens: int,
    requested_output_tokens: int | None,
    requested_total_tokens: int,
    estimated_cost_cents: int | None,
    estimated_cost_micro_cents: int | None,
) -> RuntimeLimitResult:
    base = {
        "limit": limit,
        "counter_key": counter_key,
        "counting_unit": counting_unit,
        "window_descriptor": window_descriptor,
    }
    if limit.limit_type == "requests":
        attempted = 1
        if request_count + attempted > limit.limit_value:
            return RuntimeLimitResult(
                **base,
                current_usage=request_count,
                active_reserved_usage=0,
                attempted_usage=attempted,
                would_deny=True,
                reason_code="request_limit",
                message="limit policy request limit exceeded",
            )
        reserved = reservations.requests
        if request_count + reserved + attempted > limit.limit_value:
            return RuntimeLimitResult(
                **base,
                current_usage=request_count,
                active_reserved_usage=reserved,
                attempted_usage=attempted,
                would_deny=True,
                reason_code="request_limit",
                message="limit policy request limit exceeded",
            )
        return _allowed_usage_result(
            **base,
            current_usage=request_count,
            reserved=reserved,
            attempted=attempted,
        )
    if limit.limit_type == "input_tokens":
        current = prompt_tokens
        reserved = reservations.prompt_tokens
        attempted = estimated_input_tokens
        if current + reserved + attempted > limit.limit_value:
            return _denied_usage_result(
                **base,
                reason_code="input_token_limit",
                message="limit policy input token limit exceeded",
                current_usage=current,
                reserved=reserved,
                attempted=attempted,
            )
        return _allowed_usage_result(
            **base,
            current_usage=current,
            reserved=reserved,
            attempted=attempted,
        )
    if limit.limit_type == "output_tokens" and requested_output_tokens is not None:
        current = completion_tokens
        reserved = reservations.completion_tokens
        attempted = requested_output_tokens
        if current + reserved + attempted > limit.limit_value:
            return _denied_usage_result(
                **base,
                reason_code="output_token_limit",
                message="limit policy output token limit exceeded",
                current_usage=current,
                reserved=reserved,
                attempted=attempted,
            )
        return _allowed_usage_result(
            **base,
            current_usage=current,
            reserved=reserved,
            attempted=attempted,
        )
    if limit.limit_type == "budget_cents":
        if estimated_cost_micro_cents is None:
            return _denied_usage_result(
                **base,
                reason_code="budget_unpriced",
                message="budget limit cannot be enforced: model has no configured pricing",
                current_usage=cost_cents,
                reserved=reservations.cost_cents,
                attempted=None,
            )
        if (
            cost_micro_cents + reservations.cost_micro_cents + estimated_cost_micro_cents
            > limit.limit_value * 1_000_000
        ):
            return _denied_usage_result(
                **base,
                reason_code="budget_limit",
                message="limit policy budget exceeded",
                current_usage=cost_cents,
                reserved=reservations.cost_cents,
                attempted=estimated_cost_cents,
            )
        return _allowed_usage_result(
            **base,
            current_usage=cost_cents,
            reserved=reservations.cost_cents,
            attempted=estimated_cost_cents,
        )
    if limit.limit_type == "total_tokens":
        current = prompt_tokens + completion_tokens
        reserved = reservations.prompt_tokens + reservations.completion_tokens
        if current + reserved + requested_total_tokens > limit.limit_value:
            return _denied_usage_result(
                **base,
                reason_code="total_token_limit",
                message="limit policy total token limit exceeded",
                current_usage=current,
                reserved=reserved,
                attempted=requested_total_tokens,
            )
        return _allowed_usage_result(
            **base,
            current_usage=current,
            reserved=reserved,
            attempted=requested_total_tokens,
        )
    return _allowed_usage_result(**base, current_usage=None, reserved=None, attempted=None)


def _limit_counter_starts_at_zero(limit: ResolvedLimitPolicy) -> bool:
    return (
        limit.limit_policy_id is None
        or limit.limit_policy_rule_id is None
        or limit.limit_policy_assignment_id is None
    )


def _denied_result(
    *,
    limit: ResolvedLimitPolicy,
    reason_code: str,
    message: str,
    current_usage: int | None,
    active_reserved_usage: int | None,
    attempted_usage: int | None,
) -> RuntimeLimitResult:
    return RuntimeLimitResult(
        limit=limit,
        counter_key=None,
        counting_unit="logical_request",
        window_descriptor=limit_policy_window_descriptor(limit),
        current_usage=current_usage,
        active_reserved_usage=active_reserved_usage,
        attempted_usage=attempted_usage,
        would_deny=True,
        reason_code=reason_code,
        message=message,
    )


def _denied_usage_result(
    **kwargs,
) -> RuntimeLimitResult:
    return RuntimeLimitResult(
        current_usage=kwargs.pop("current_usage"),
        active_reserved_usage=kwargs.pop("reserved"),
        attempted_usage=kwargs.pop("attempted"),
        would_deny=True,
        reason_code=kwargs.pop("reason_code"),
        message=kwargs.pop("message"),
        **kwargs,
    )


def _allowed_usage_result(
    *,
    current_usage: int | None,
    reserved: int | None,
    attempted: int | None,
    **kwargs,
) -> RuntimeLimitResult:
    return RuntimeLimitResult(
        current_usage=current_usage,
        active_reserved_usage=reserved,
        attempted_usage=attempted,
        would_deny=False,
        reason_code=None,
        message=None,
        **kwargs,
    )


def limit_dimension_subject(
    *,
    resolved: Any,
    gateway_endpoint: str | None,
) -> dict[str, Any]:
    return {
        "org_id": resolved.org_id,
        "team_id": resolved.team_id,
        "project_id": resolved.project_id,
        "virtual_key_id": resolved.virtual_key_id,
        "provider_id": resolved.provider_id,
        "credential_pool_id": resolved.pool_id,
        "provider_credential_id": resolved.provider_key_id,
        "provider_model_offering_id": resolved.model_offering_id,
        "public_model_id": resolved.public_model_id,
        "public_model_name": resolved.public_model_name,
        "route_candidate_id": resolved.route_candidate_id,
        "access_policy_id": resolved.access_policy_id,
        "access_policy_revision_id": resolved.access_policy_revision_id,
        "gateway_endpoint": gateway_endpoint,
        "requested_model": resolved.requested_model,
    }


async def limit_rule_matches_runtime_subject(
    *,
    limit: ResolvedLimitPolicy,
    subject: dict[str, Any],
    db: AsyncSession,
) -> bool:
    matchers = await _limit_rule_matchers(limit=limit, org_id=subject["org_id"], db=db)
    for matcher in matchers:
        if not evaluate_matcher(
            subject=subject,
            dimension=_limit_policy_dimension_value(matcher, "dimension"),
            operator=_limit_policy_dimension_value(matcher, "operator"),
            value=_limit_policy_dimension_value(matcher, "value_json"),
            stage=PolicyDimensionStage.LIMIT_RESERVATION,
        ):
            return False
    return True


async def limit_rule_counter_key(
    *,
    limit: ResolvedLimitPolicy,
    subject: dict[str, Any],
    db: AsyncSession,
) -> str | None:
    partitions = await _limit_rule_partitions(limit=limit, org_id=subject["org_id"], db=db)
    if not partitions:
        return None
    return "|".join(
        f"{_limit_policy_dimension_value(partition, 'dimension')}="
        f"{subject.get(_limit_policy_dimension_value(partition, 'dimension'))}"
        for partition in partitions
    )


async def limit_rule_counter_identity(
    *,
    org_id: UUID,
    limit: ResolvedLimitPolicy,
    subject: dict[str, Any],
    db: AsyncSession,
) -> str:
    counter_key = await limit_rule_counter_key(limit=limit, subject=subject, db=db)
    counting_unit = await limit_rule_counting_unit(org_id=org_id, limit=limit, db=db)
    window_descriptor = limit_policy_window_descriptor(limit)
    return "|".join(
        (
            str(org_id),
            str(limit.limit_policy_id),
            str(limit.limit_policy_rule_id),
            str(limit.limit_policy_assignment_id),
            window_descriptor,
            counting_unit,
            counter_key or "unpartitioned",
        )
    )


async def limit_rule_counting_unit(
    *,
    org_id: UUID,
    limit: ResolvedLimitPolicy,
    db: AsyncSession,
) -> str:
    if limit.limit_type != "requests":
        return "logical_request"
    matchers = await _limit_rule_matchers(limit=limit, org_id=org_id, db=db)
    partitions = await _limit_rule_partitions(limit=limit, org_id=org_id, db=db)
    dimensions = {_limit_policy_dimension_value(matcher, "dimension") for matcher in matchers} | {
        _limit_policy_dimension_value(partition, "dimension") for partition in partitions
    }
    if dimensions & ATTEMPT_SCOPED_DIMENSIONS:
        return "route_attempt"
    return "logical_request"


async def _limit_rule_matchers(*, limit: ResolvedLimitPolicy, org_id: UUID, db: AsyncSession):
    if limit.draft_ref is not None:
        return limit.matchers
    if limit.limit_policy_rule_id is None:
        return limit.matchers
    return await policies_repository.list_limit_policy_rule_matchers(
        org_id=org_id,
        rule_id=limit.limit_policy_rule_id,
        db=db,
    )


async def _limit_rule_partitions(*, limit: ResolvedLimitPolicy, org_id: UUID, db: AsyncSession):
    if limit.draft_ref is not None:
        return limit.partitions
    if limit.limit_policy_rule_id is None:
        return limit.partitions
    return await policies_repository.list_limit_policy_rule_partitions(
        org_id=org_id,
        rule_id=limit.limit_policy_rule_id,
        db=db,
    )


def _limit_policy_dimension_value(item, field: str):
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field)


def limit_policy_window_start(interval_unit: str, interval_count: int) -> datetime | None:
    now = datetime.now(UTC)
    if interval_unit == "minute":
        return now - timedelta(minutes=interval_count)
    if interval_unit == "hour":
        return now - timedelta(hours=interval_count)
    if interval_unit == "day":
        return now - timedelta(days=interval_count)
    if interval_unit == "week":
        return now - timedelta(weeks=interval_count)
    if interval_unit == "month":
        return subtract_months(now, interval_count)
    return None


def limit_policy_window_descriptor(limit: ResolvedLimitPolicy) -> str:
    if limit.interval_unit == "lifetime":
        return f"{limit.interval_unit}:{limit.interval_count}:lifetime"
    return f"{limit.interval_unit}:{limit.interval_count}:rolling"
