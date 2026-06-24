import csv
from datetime import datetime
from io import StringIO
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_current_user,
    get_scope,
)
from app.core.csv_safe import sanitize_csv_cell
from app.core.database import Scope, get_db
from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import ActivityEventResponse
from app.modules.auth import facade as auth_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.usage import facade
from app.modules.usage.schemas import (
    GatewayRequestTraceListResponse,
    GatewayRequestTraceResponse,
    OrganizationUsageSummary,
    SpendInsights,
    UsageFilterOptions,
    UsageRecordResponse,
    UsageTimeSeriesPoint,
)
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import WorkspaceScopeNotFoundError
from app.modules.workspace.schemas import WorkspaceProjectIdentity

router = APIRouter(prefix="/usage", tags=["usage"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
UsageWindow = Literal["24h", "7d", "30d", "90d", "lifetime"]
UsageGrain = Literal["hour", "day", "week"]
GatewayRequestTraceStatus = Literal["succeeded", "failed", "denied", "pending"]
GatewayRequestTraceFallback = Literal["attempted", "not_attempted"]


class OrganizationUsagePage(OrganizationUsageSummary):
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
) -> OrganizationUsagePage:
    usage_scope = await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
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
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    request_id: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[UsageRecordResponse]:
    usage_scope = await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    return await facade.list_usage_records(
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
        limit=min(max(limit, 1), 500),
        offset=max(offset, 0),
        db=db,
    )


@router.get("/requests")
async def list_gateway_requests(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    window: UsageWindow = "30d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    provider_id: UUID | None = None,
    public_model_name: str | None = None,
    requested_model: str | None = None,
    request_id: str | None = None,
    status: GatewayRequestTraceStatus | None = None,
    fallback: GatewayRequestTraceFallback | None = None,
    error_code: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> GatewayRequestTraceListResponse:
    usage_scope = await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    return await facade.list_gateway_requests(
        org_id=scope.org_id,
        window=window,
        start_at=start_at,
        end_at=end_at,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        provider_id=provider_id,
        public_model_name=public_model_name,
        requested_model=requested_model,
        request_id=request_id,
        status=status,
        fallback=fallback,
        error_code=error_code,
        search=search,
        allowed_team_ids=usage_scope.allowed_team_ids,
        allowed_project_ids=usage_scope.allowed_project_ids,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
        db=db,
    )


@router.get("/requests/{gateway_request_id}")
async def get_gateway_request_trace(
    gateway_request_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> GatewayRequestTraceResponse:
    trace = await facade.get_gateway_request_trace(
        org_id=scope.org_id,
        gateway_request_id=gateway_request_id,
        db=db,
    )
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")
    await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        team_id=trace.request.team_id,
        project_id=trace.request.project_id,
        virtual_key_id=trace.request.virtual_key_id,
    )
    return trace


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
    usage_scope = await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
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
    usage_scope = await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
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
    usage_scope = await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
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
    usage_scope = await _resolve_usage_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
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


class _UsageScope:
    def __init__(
        self,
        *,
        allowed_team_ids: set[UUID] | None,
        allowed_project_ids: set[UUID] | None,
    ) -> None:
        self.allowed_team_ids = allowed_team_ids
        self.allowed_project_ids = allowed_project_ids


async def _resolve_usage_scope(
    *,
    user: AuthenticatedUser,
    org_id: UUID,
    db: AsyncSession,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> _UsageScope:
    if auth_facade.has_permission(user, "usage.view"):
        await _validate_filter_relationships(
            org_id=org_id,
            db=db,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        )
        return _UsageScope(allowed_team_ids=None, allowed_project_ids=None)

    allowed_team_ids = {membership.team_id for membership in user.team_memberships}
    allowed_project_ids = {membership.project_id for membership in user.project_memberships}
    if not allowed_team_ids and not allowed_project_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )

    project = await _validate_filter_relationships(
        org_id=org_id,
        db=db,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    if team_id is not None and team_id not in allowed_team_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )
    if project is not None and (
        project.team_id not in allowed_team_ids and project.id not in allowed_project_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient permissions",
        )
    return _UsageScope(
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
    )


async def _validate_filter_relationships(
    *,
    org_id: UUID,
    db: AsyncSession,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> WorkspaceProjectIdentity | None:
    try:
        validation = await workspace_facade.validate_filter_relationships(
            scope=Scope(org_id=org_id),
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            db=db,
        )
    except WorkspaceScopeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_filter_validation_error_detail(exc.reason),
        ) from exc
    return validation.project


def _filter_validation_error_detail(reason: str) -> str:
    if reason == "project_team_mismatch":
        return "project does not belong to team"
    if reason == "virtual_key_project_mismatch":
        return "virtual key does not belong to project"
    if reason == "virtual_key_team_mismatch":
        return "virtual key does not belong to team"
    return "insufficient permissions"
