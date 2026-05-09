from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.core.database import Scope, get_db
from app.modules.analytics import facade
from app.modules.analytics.schemas import AnalyticsSummaryResponse
from app.modules.auth.schemas import AuthenticatedUser

router = APIRouter(prefix="/analytics", tags=["analytics"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("/summary")
async def get_analytics_summary(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    recent_limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> AnalyticsSummaryResponse:
    return await facade.get_summary(scope=scope, days=days, recent_limit=recent_limit, db=db)
