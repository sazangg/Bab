from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_current_user,
    get_scope,
    require_permission,
    require_project_view_or_permission,
    require_team_view_or_permission,
)
from app.core.database import Scope, get_db
from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import ActivityEventResponse
from app.modules.auth import facade as auth_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.usage import facade
from app.modules.usage.schemas import (
    OrganizationUsageSummary,
    SpendInsights,
    UsageRecordResponse,
    UsageTimeSeriesPoint,
)

router = APIRouter(prefix="/usage", tags=["usage"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
UsageViewer = Annotated[AuthenticatedUser, Depends(require_permission("usage.view"))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
UsageWindow = Literal["24h", "7d", "30d", "90d", "lifetime"]
UsageGrain = Literal["hour", "day", "week"]


class OrganizationUsagePage(OrganizationUsageSummary):
    recent_denials: list[ActivityEventResponse]


@router.get("/summary")
async def get_organization_usage_summary(
    scope: RequestScope,
    db: DatabaseSession,
    _: UsageViewer,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
) -> OrganizationUsagePage:
    summary = await facade.get_organization_usage_summary(
        org_id=scope.org_id,
        window=window,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        db=db,
    )
    recent_denials = await activity_facade.list_events(
        org_id=scope.org_id,
        category="proxy",
        severity=None,
        entity_type=None,
        entity_id=None,
        since=start_at or facade.window_start(window),
        limit=20,
        db=db,
    )
    return OrganizationUsagePage(
        **summary.model_dump(),
        recent_denials=recent_denials,
    )


@router.get("/records")
async def list_usage_records(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    allocation_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    limit: int = 100,
) -> list[UsageRecordResponse]:
    if not auth_facade.has_permission(user, "usage.view"):
        if team_id is not None:
            await require_team_view_or_permission(
                team_id=str(team_id),
                permission="usage.view",
                user=user,
                db=db,
            )
        elif project_id is not None:
            await require_project_view_or_permission(
                project_id=str(project_id),
                permission="usage.view",
                user=user,
                db=db,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )
    return await facade.list_usage_records(
        org_id=scope.org_id,
        window=window,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        allocation_id=allocation_id,
        virtual_key_id=virtual_key_id,
        model=model,
        limit=min(max(limit, 1), 500),
        db=db,
    )


@router.get("/timeseries")
async def get_organization_usage_timeseries(
    scope: RequestScope,
    db: DatabaseSession,
    _: UsageViewer,
    window: UsageWindow = "30d",
    grain: UsageGrain = "day",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
) -> list[UsageTimeSeriesPoint]:
    return await facade.get_organization_usage_timeseries(
        org_id=scope.org_id,
        window=window,
        grain=grain,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        db=db,
    )


@router.get("/spend-insights")
async def get_spend_insights(
    scope: RequestScope,
    db: DatabaseSession,
    _: UsageViewer,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
) -> SpendInsights:
    return await facade.get_spend_insights(
        org_id=scope.org_id,
        window=window,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        db=db,
    )
