from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.limits.errors import LimitExceededError, LimitPolicyNotFoundError
from app.modules.limits.internal import repository
from app.modules.limits.internal.models import LimitPolicy
from app.modules.limits.schemas import (
    CreateLimitPolicyRequest,
    LimitEvaluationContext,
    LimitPolicyResponse,
    UpdateLimitPolicyRequest,
)

REQUEST_COUNT = "request_count"
TOKEN_COUNT = "token_count"
SUPPORTED_SCOPE_TYPES = {"org", "project", "provider", "provider_model", "virtual_key"}
SUPPORTED_METRICS = {REQUEST_COUNT, TOKEN_COUNT}
SUPPORTED_WINDOWS = {"minute", "day"}


@dataclass(frozen=True)
class LimitReservation:
    policy_id: UUID
    window_start: datetime
    metric: str
    reserved_amount: int


async def create_policy(
    *,
    payload: CreateLimitPolicyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> LimitPolicyResponse:
    del actor
    _validate_policy_shape(
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        scope_value=payload.scope_value,
        metric=payload.metric,
        window=payload.window,
    )
    async with transaction(db):
        policy = await repository.create_policy(org_id=scope.org_id, payload=payload, db=db)
    return _to_response(policy)


async def list_policies(*, scope: Scope, db: AsyncSession) -> list[LimitPolicyResponse]:
    policies = await repository.list_policies(org_id=scope.org_id, db=db)
    return [_to_response(policy) for policy in policies]


async def update_policy(
    *,
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> LimitPolicyResponse:
    del actor
    async with transaction(db):
        policy = await _get_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        next_scope_type = (
            payload.scope_type if payload.scope_type is not None else policy.scope_type
        )
        next_scope_id = (
            payload.scope_id if "scope_id" in payload.model_fields_set else policy.scope_id
        )
        next_scope_value = (
            payload.scope_value if "scope_value" in payload.model_fields_set else policy.scope_value
        )
        next_metric = payload.metric if payload.metric is not None else policy.metric
        next_window = payload.window if payload.window is not None else policy.window

        _validate_policy_shape(
            scope_type=next_scope_type,
            scope_id=next_scope_id,
            scope_value=next_scope_value,
            metric=next_metric,
            window=next_window,
        )

        policy.scope_type = next_scope_type
        policy.scope_id = next_scope_id
        policy.scope_value = next_scope_value
        policy.metric = next_metric
        policy.window = next_window
        if payload.limit_value is not None:
            policy.limit_value = payload.limit_value
        if payload.is_active is not None:
            policy.is_active = payload.is_active

    return _to_response(policy)


async def deactivate_policy(
    *,
    policy_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    del actor
    async with transaction(db):
        policy = await _get_policy_or_raise(policy_id=policy_id, scope=scope, db=db)
        policy.is_active = False


async def reserve_proxy_limits(
    *,
    context: LimitEvaluationContext,
    estimated_tokens: int,
    db: AsyncSession,
    now: datetime | None = None,
) -> list[LimitReservation]:
    checked_at = _as_utc(now or datetime.now(UTC))
    policies = await repository.list_matching_policies(
        context=context,
        metrics={REQUEST_COUNT, TOKEN_COUNT},
        db=db,
    )
    reservations: list[LimitReservation] = []
    async with transaction(db):
        for policy in policies:
            amount = _reservation_amount(policy=policy, estimated_tokens=estimated_tokens)
            window_start = _window_start(checked_at, policy.window)
            allowed = await repository.reserve_if_below_limit(
                policy=policy,
                window_start=window_start,
                amount=amount,
                db=db,
            )
            if not allowed:
                raise LimitExceededError
            reservations.append(
                LimitReservation(
                    policy_id=policy.id,
                    window_start=window_start,
                    metric=policy.metric,
                    reserved_amount=amount,
                )
            )

    return reservations


async def reconcile_token_limits(
    *,
    reservations: list[LimitReservation],
    actual_tokens: int,
    estimated_tokens: int,
    db: AsyncSession,
) -> None:
    delta = actual_tokens - estimated_tokens
    if delta == 0:
        return

    async with transaction(db):
        for reservation in reservations:
            if (
                reservation.metric == TOKEN_COUNT
                and reservation.reserved_amount == estimated_tokens
            ):
                await repository.adjust_counter(
                    policy_id=reservation.policy_id,
                    window_start=reservation.window_start,
                    delta=delta,
                    db=db,
                )


def _reservation_amount(*, policy: LimitPolicy, estimated_tokens: int) -> int:
    if policy.metric == REQUEST_COUNT:
        return 1
    if policy.metric == TOKEN_COUNT:
        return estimated_tokens
    raise ValueError(f"unsupported limit metric: {policy.metric}")


def _window_start(value: datetime, window: str) -> datetime:
    if window == "minute":
        return value.replace(second=0, microsecond=0)
    if window == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unsupported limit window: {window}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _get_policy_or_raise(*, policy_id: UUID, scope: Scope, db: AsyncSession) -> LimitPolicy:
    policy = await repository.get_policy(policy_id=policy_id, org_id=scope.org_id, db=db)
    if policy is None:
        raise LimitPolicyNotFoundError
    return policy


def _validate_policy_shape(
    *,
    scope_type: str,
    scope_id: UUID | None,
    scope_value: str | None,
    metric: str,
    window: str,
) -> None:
    if scope_type not in SUPPORTED_SCOPE_TYPES:
        raise ValueError(f"unsupported limit scope type: {scope_type}")
    if metric not in SUPPORTED_METRICS:
        raise ValueError(f"unsupported limit metric: {metric}")
    if window not in SUPPORTED_WINDOWS:
        raise ValueError(f"unsupported limit window: {window}")
    if scope_id is None:
        raise ValueError(f"{scope_type} limit policies require scope_id")
    if scope_type == "provider_model" and not scope_value:
        raise ValueError("provider_model limit policies require scope_value")
    if scope_type != "provider_model" and scope_value is not None:
        raise ValueError("scope_value is only supported for provider_model policies")


def _to_response(policy: LimitPolicy) -> LimitPolicyResponse:
    return LimitPolicyResponse.model_validate(policy)
