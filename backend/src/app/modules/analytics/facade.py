from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.analytics.internal import service
from app.modules.analytics.schemas import AnalyticsSummaryResponse


async def get_summary(
    *,
    scope: Scope,
    days: int,
    recent_limit: int,
    db: AsyncSession,
) -> AnalyticsSummaryResponse:
    return await service.get_summary(scope=scope, days=days, recent_limit=recent_limit, db=db)
