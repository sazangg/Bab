from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transaction
from app.modules.limits.errors import LimitExceededError
from app.modules.limits.internal import repository
from app.modules.limits.internal.models import LimitPolicy
from app.modules.limits.schemas import LimitEvaluationContext

REQUEST_COUNT = "request_count"
TOKEN_COUNT = "token_count"


@dataclass(frozen=True)
class LimitReservation:
    policy_id: UUID
    window_start: datetime
    metric: str
    reserved_amount: int


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
