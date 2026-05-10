from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.limits.internal import service
from app.modules.limits.internal.service import LimitReservation
from app.modules.limits.schemas import (
    CreateLimitPolicyRequest,
    LimitEvaluationContext,
    LimitPolicyResponse,
    UpdateLimitPolicyRequest,
)


async def create_policy(
    *,
    payload: CreateLimitPolicyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> LimitPolicyResponse:
    return await service.create_policy(payload=payload, actor=actor, scope=scope, db=db)


async def list_policies(*, scope: Scope, db: AsyncSession) -> list[LimitPolicyResponse]:
    return await service.list_policies(scope=scope, db=db)


async def update_policy(
    *,
    policy_id: UUID,
    payload: UpdateLimitPolicyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> LimitPolicyResponse:
    return await service.update_policy(
        policy_id=policy_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_policy(
    *,
    policy_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_policy(policy_id=policy_id, actor=actor, scope=scope, db=db)


async def reserve_proxy_limits(
    *,
    context: LimitEvaluationContext,
    estimated_tokens: int,
    db: AsyncSession,
    now: datetime | None = None,
) -> list[LimitReservation]:
    return await service.reserve_proxy_limits(
        context=context,
        estimated_tokens=estimated_tokens,
        db=db,
        now=now,
    )


async def reconcile_token_limits(
    *,
    reservations: list[LimitReservation],
    actual_tokens: int,
    estimated_tokens: int,
    db: AsyncSession,
) -> None:
    await service.reconcile_token_limits(
        reservations=reservations,
        actual_tokens=actual_tokens,
        estimated_tokens=estimated_tokens,
        db=db,
    )
