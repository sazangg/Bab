from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope
from app.api.v1.routes.workspace_filters import resolve_workspace_filter_scope
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization.permissions import Permissions
from app.modules.gateway_history import facade
from app.modules.gateway_history.schemas import (
    GatewayRequestTraceListResponse,
    GatewayRequestTraceResponse,
)

router = APIRouter(prefix="/gateway-history", tags=["gateway-history"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
UsageWindow = Literal["24h", "7d", "30d", "90d", "lifetime"]
GatewayRequestTraceStatus = Literal["succeeded", "failed", "denied", "pending"]
GatewayRequestTraceFallback = Literal["attempted", "not_attempted"]


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
    history_scope = await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.GATEWAY_HISTORY_VIEW,
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
        allowed_team_ids=history_scope.allowed_team_ids,
        allowed_project_ids=history_scope.allowed_project_ids,
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
    await resolve_workspace_filter_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        global_permission=Permissions.GATEWAY_HISTORY_VIEW,
        team_id=trace.request.team_id,
        project_id=trace.request.project_id,
        virtual_key_id=trace.request.virtual_key_id,
    )
    return trace
