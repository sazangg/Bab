from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.internal.models import LimitCounter, LimitPolicy
from app.modules.limits.schemas import LimitEvaluationContext


async def list_matching_policies(
    *,
    context: LimitEvaluationContext,
    metrics: set[str],
    db: AsyncSession,
) -> list[LimitPolicy]:
    result = await db.scalars(
        select(LimitPolicy).where(
            LimitPolicy.org_id == context.org_id,
            LimitPolicy.is_active.is_(True),
            LimitPolicy.metric.in_(metrics),
            or_(
                and_(LimitPolicy.scope_type == "org", LimitPolicy.scope_id == context.org_id),
                and_(
                    LimitPolicy.scope_type == "project", LimitPolicy.scope_id == context.project_id
                ),
                and_(
                    LimitPolicy.scope_type == "provider",
                    LimitPolicy.scope_id == context.provider_id,
                ),
                and_(
                    LimitPolicy.scope_type == "provider_model",
                    LimitPolicy.scope_id == context.provider_id,
                    LimitPolicy.scope_value == context.provider_model,
                ),
                and_(
                    LimitPolicy.scope_type == "virtual_key",
                    LimitPolicy.scope_id == context.virtual_key_id,
                ),
            ),
        )
    )
    return list(result)


async def reserve_if_below_limit(
    *,
    policy: LimitPolicy,
    window_start: datetime,
    amount: int,
    db: AsyncSession,
) -> bool:
    updated = await _increment_existing_counter_if_below_limit(
        policy_id=policy.id,
        window_start=window_start,
        amount=amount,
        limit=policy.limit_value,
        db=db,
    )
    if updated:
        return True

    existing = await _get_counter(policy_id=policy.id, window_start=window_start, db=db)
    if existing is not None:
        return False

    counter = LimitCounter(
        org_id=policy.org_id,
        policy_id=policy.id,
        window_start=window_start,
        consumed_amount=amount,
    )
    try:
        async with db.begin_nested():
            db.add(counter)
            await db.flush()
        return True
    except IntegrityError:
        return await _increment_existing_counter_if_below_limit(
            policy_id=policy.id,
            window_start=window_start,
            amount=amount,
            limit=policy.limit_value,
            db=db,
        )


async def adjust_counter(
    *,
    policy_id: UUID,
    window_start: datetime,
    delta: int,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(LimitCounter)
        .where(LimitCounter.policy_id == policy_id, LimitCounter.window_start == window_start)
        .values(consumed_amount=LimitCounter.consumed_amount + delta)
    )


async def _increment_existing_counter_if_below_limit(
    *,
    policy_id: UUID,
    window_start: datetime,
    amount: int,
    limit: int,
    db: AsyncSession,
) -> bool:
    result = await db.execute(
        update(LimitCounter)
        .where(
            LimitCounter.policy_id == policy_id,
            LimitCounter.window_start == window_start,
            LimitCounter.consumed_amount + amount <= limit,
        )
        .values(consumed_amount=LimitCounter.consumed_amount + amount)
    )
    return result.rowcount == 1


async def _get_counter(
    *,
    policy_id: UUID,
    window_start: datetime,
    db: AsyncSession,
) -> LimitCounter | None:
    return await db.scalar(
        select(LimitCounter).where(
            LimitCounter.policy_id == policy_id,
            LimitCounter.window_start == window_start,
        )
    )
