from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.core.database import Scope, get_db
from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import ActivityEventResponse
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.usage import facade
from app.modules.usage.schemas import OrganizationUsageSummary

router = APIRouter(prefix="/usage", tags=["usage"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
UsageWindow = Literal["24h", "7d", "30d", "lifetime"]


class OrganizationUsagePage(OrganizationUsageSummary):
    recent_denials: list[ActivityEventResponse]


@router.get("/summary")
async def get_organization_usage_summary(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
    window: UsageWindow = "30d",
) -> OrganizationUsagePage:
    summary = await facade.get_organization_usage_summary(
        org_id=scope.org_id,
        window=window,
        db=db,
    )
    recent_denials = await activity_facade.list_events(
        org_id=scope.org_id,
        category="proxy",
        severity=None,
        entity_type=None,
        entity_id=None,
        since=facade.window_start(window),
        limit=20,
        db=db,
    )
    return OrganizationUsagePage(
        **summary.model_dump(),
        recent_denials=recent_denials,
    )
