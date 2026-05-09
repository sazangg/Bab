from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.internal import service
from app.modules.limits.internal.service import LimitReservation
from app.modules.limits.schemas import LimitEvaluationContext


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
