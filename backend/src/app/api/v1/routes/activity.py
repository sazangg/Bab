import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.csv_exports import require_export_within_limit
from app.api.v1.deps import get_current_user, get_scope
from app.core.csv_safe import CSV_EXPORT_MAX_ROWS, stream_csv_rows
from app.core.database import Scope, get_db
from app.modules.activity import facade
from app.modules.activity.schemas import ActivityEventPageResponse
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.permissions import Permissions
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import WorkspaceScopeNotFoundError
from app.modules.workspace.schemas import WorkspaceProjectIdentity

router = APIRouter(prefix="/activity", tags=["activity"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.get("")
async def list_activity_events(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    category: str | None = None,
    severity: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    q: str | None = Query(default=None, max_length=200),
    before_at: datetime | None = None,
    before_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=100),
) -> ActivityEventPageResponse:
    team_id, project_id, virtual_key_id = _merge_entity_filter(
        entity_type=entity_type,
        entity_id=entity_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    activity_scope = await _resolve_activity_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    events = await facade.list_events(
        org_id=scope.org_id,
        category=category,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        allowed_team_ids=activity_scope.allowed_team_ids,
        allowed_project_ids=activity_scope.allowed_project_ids,
        since=start_at,
        end_at=end_at,
        search=q.strip() if q and q.strip() else None,
        before_at=before_at,
        before_id=before_id,
        limit=limit + 1,
        db=db,
    )
    items = events[:limit]
    has_more = len(events) > limit
    next_item = items[-1] if has_more and items else None
    return ActivityEventPageResponse(
        items=items,
        limit=limit,
        has_more=has_more,
        next_before_at=next_item.created_at if next_item else None,
        next_before_id=next_item.id if next_item else None,
    )


@router.get("/export")
async def export_activity_events(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
    category: str | None = None,
    severity: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> Response:
    team_id, project_id, virtual_key_id = _merge_entity_filter(
        entity_type=entity_type,
        entity_id=entity_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    activity_scope = await _resolve_activity_scope(
        user=user,
        org_id=scope.org_id,
        db=db,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
    )
    events = await facade.list_events(
        org_id=scope.org_id,
        category=category,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        allowed_team_ids=activity_scope.allowed_team_ids,
        allowed_project_ids=activity_scope.allowed_project_ids,
        since=start_at,
        end_at=end_at,
        search=q.strip() if q and q.strip() else None,
        limit=CSV_EXPORT_MAX_ROWS + 1,
        db=db,
    )
    require_export_within_limit(events)
    return StreamingResponse(
        stream_csv_rows(
            header=[
                "id",
                "created_at",
                "request_id",
                "category",
                "severity",
                "action",
                "message",
                "actor_user_id",
                "actor_email",
                "team_id",
                "project_id",
                "virtual_key_id",
                "provider_id",
                "pool_id",
                "model_offering_id",
                "metadata",
            ],
            rows=(
                (
                    event.id,
                    event.created_at,
                    event.request_id,
                    event.category,
                    event.severity,
                    event.action,
                    event.message,
                    event.actor_user_id,
                    event.actor_email,
                    event.team_id,
                    event.project_id,
                    event.virtual_key_id,
                    event.provider_id,
                    event.pool_id,
                    event.model_offering_id,
                    json.dumps(event.metadata, sort_keys=True, default=str),
                )
                for event in events
            ),
        ),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bab-activity-events.csv"'},
    )


class _ActivityScope:
    def __init__(
        self,
        *,
        allowed_team_ids: set[UUID] | None,
        allowed_project_ids: set[UUID] | None,
    ) -> None:
        self.allowed_team_ids = allowed_team_ids
        self.allowed_project_ids = allowed_project_ids


async def _resolve_activity_scope(
    *,
    user: AuthenticatedUser,
    org_id: UUID,
    db: AsyncSession,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> _ActivityScope:
    if authorization_facade.has_permission(user, Permissions.ACTIVITY_VIEW):
        await _validate_filter_relationships(
            org_id=org_id,
            db=db,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        )
        return _ActivityScope(allowed_team_ids=None, allowed_project_ids=None)

    allowed_scopes = authorization_facade.authorized_workspace_ids(user, relationship="member")
    allowed_team_ids = allowed_scopes.team_ids
    allowed_project_ids = allowed_scopes.project_ids
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
    return _ActivityScope(
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
    )


def _merge_entity_filter(
    *,
    entity_type: str | None,
    entity_id: UUID | None,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    if entity_type is None or entity_id is None:
        return team_id, project_id, virtual_key_id
    mapped = {
        "team": team_id,
        "project": project_id,
        "virtual_key": virtual_key_id,
    }.get(entity_type)
    if mapped is not None and mapped != entity_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="conflicting entity filter",
        )
    if entity_type == "team":
        team_id = entity_id
    elif entity_type == "project":
        project_id = entity_id
    elif entity_type == "virtual_key":
        virtual_key_id = entity_id
    return team_id, project_id, virtual_key_id


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
