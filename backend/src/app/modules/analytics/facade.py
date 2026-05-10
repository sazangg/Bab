from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.analytics.internal import service
from app.modules.analytics.internal.service import AnalyticsKeyNotFoundError
from app.modules.analytics.schemas import AnalyticsKeyUsageResponse, AnalyticsSummaryResponse

__all__ = ["AnalyticsKeyNotFoundError", "get_key_usage", "get_summary"]


async def get_summary(
    *,
    scope: Scope,
    days: int,
    recent_limit: int,
    db: AsyncSession,
) -> AnalyticsSummaryResponse:
    return await service.get_summary(scope=scope, days=days, recent_limit=recent_limit, db=db)


async def get_key_usage(
    *,
    scope: Scope,
    virtual_key_id: UUID,
    days: int,
    recent_limit: int,
    db: AsyncSession,
) -> AnalyticsKeyUsageResponse:
    return await service.get_key_usage(
        scope=scope,
        virtual_key_id=virtual_key_id,
        days=days,
        recent_limit=recent_limit,
        db=db,
    )
