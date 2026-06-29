import csv
from datetime import datetime
from io import StringIO
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_current_user,
    get_scope,
)
from app.api.v1.routes.workspace_filters import resolve_workspace_filter_scope
from app.core.csv_safe import sanitize_csv_cell
from app.core.database import Scope, get_db
from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import ActivityEventResponse
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization.permissions import Permissions
from app.modules.usage import facade
from app.modules.usage.schemas import (
    OrganizationUsageSummary,
    SpendInsights,
    UsageFilterOptions,
    UsageRecordPageResponse,
    UsageTimeSeriesPoint,
)

router = APIRouter(prefix="/usage", tags=["usage"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
UsageWindow = Literal["24h", "7d", "30d", "90d", "lifetime"]
UsageGrain = Literal["hour", "day", "week"]


class OrganizationUsagePageResponse(OrganizationUsageSummary):
    recent_denials: list[ActivityEventResponse]


@router.get("/summary")
async def get_organization_usage_summary(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
) -> OrganizationUsagePageResponse:
    usage_scope = await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.USAGE_VIEW,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
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
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        db=db,
    )
    recent_denials = await activity_facade.list_events(
        org_id=scope.org_id,
        category="proxy",
        severity=None,
        entity_type=None,
        entity_id=None,
        since=start_at or facade.window_start(window),
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        limit=20,
        db=db,
    )
    return OrganizationUsagePageResponse(
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
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    request_id: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> UsageRecordPageResponse:
    usage_scope = await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.USAGE_VIEW,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    records = await facade.list_usage_records(
        org_id=scope.org_id,
        window=window,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=request_id,
        search=search,
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        limit=limit + 1,
        offset=offset,
        db=db,
    )
    return UsageRecordPageResponse(
        items=records[:limit],
        limit=limit,
        offset=offset,
        has_more=len(records) > limit,
    )


@router.get("/records/export")
async def export_usage_records(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    request_id: str | None = None,
    search: str | None = None,
) -> Response:
    usage_scope = await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.USAGE_VIEW,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    records = await facade.list_usage_records(
        org_id=scope.org_id,
        window=window,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=request_id,
        search=search,
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        limit=None,
        offset=0,
        db=db,
    )
    return _csv_response(
        filename="bab-usage-records.csv",
        header=[
            "id",
            "created_at",
            "request_id",
            "org_id",
            "team_id",
            "project_id",
            "access_policy_id",
            "access_policy_route_id",
            "limit_policy_ids",
            "virtual_key_id",
            "pool_id",
            "provider_id",
            "provider_credential_id",
            "provider_credential_name",
            "provider_credential_prefix",
            "requested_model",
            "provider_model",
            "http_status",
            "latency_ms",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cost_cents",
            "confirmed_spend_cents",
            "estimated_spend_cents",
            "spend_type",
            "usage_source",
            "error_code",
        ],
        rows=[
            [
                record.id,
                record.created_at,
                record.request_id,
                record.org_id,
                record.team_id,
                record.project_id,
                record.access_policy_id,
                record.access_policy_route_id,
                "|".join(record.limit_policy_ids or []),
                record.virtual_key_id,
                record.pool_id,
                record.provider_id,
                record.provider_credential_id,
                record.provider_credential_name,
                record.provider_credential_prefix,
                record.requested_model,
                record.provider_model,
                record.http_status,
                record.latency_ms,
                record.prompt_tokens,
                record.completion_tokens,
                record.total_tokens,
                record.cost_cents,
                record.confirmed_spend_cents,
                record.estimated_spend_cents,
                record.spend_type,
                record.usage_source,
                record.error_code,
            ]
            for record in records
        ],
    )


@router.get("/timeseries")
async def get_organization_usage_timeseries(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
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
    usage_scope = await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.USAGE_VIEW,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
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
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        db=db,
    )


def _csv_response(*, filename: str, header: list[str], rows: list[list[object]]) -> Response:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows([sanitize_csv_cell(cell) for cell in row] for row in rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/filter-options")
async def get_usage_filter_options(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
) -> UsageFilterOptions:
    usage_scope = await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.USAGE_VIEW,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=None,
    )
    return await facade.get_usage_filter_options(
        org_id=scope.org_id,
        window=window,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        project_id=project_id,
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        db=db,
    )


@router.get("/spend-insights")
async def get_spend_insights(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
) -> SpendInsights:
    usage_scope = await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.USAGE_VIEW,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
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
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        db=db,
    )

