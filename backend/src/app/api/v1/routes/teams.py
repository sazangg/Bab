from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_current_user,
    get_scope,
    require_permission,
    require_team_admin_or_permission,
    require_team_view_or_permission,
)
from app.core.database import Scope, get_db
from app.modules.auth import facade as auth_facade
from app.modules.auth.errors import (
    InvalidAccessTokenError,
    MemberNotFoundError,
    PermissionDeniedError,
)
from app.modules.auth.schemas import (
    AuthenticatedUser,
    MemberOptionResponse,
    TeamMemberResponse,
    UpdateTeamMemberRequest,
    UpsertTeamMemberRequest,
)
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.permissions import Permissions
from app.modules.usage import facade as usage_facade
from app.modules.usage.schemas import OrganizationUsageSummary
from app.modules.workspace import facade
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import (
    ProjectSlugAlreadyExistsError,
    TeamInactiveError,
    TeamNotFoundError,
    TeamSlugAlreadyExistsError,
)
from app.modules.workspace.schemas import (
    CreateProjectRequest,
    CreateTeamRequest,
    ProjectResponse,
    TeamArchiveImpactResponse,
    TeamResponse,
    UpdateTeamRequest,
)

router = APIRouter(prefix="/teams", tags=["teams"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
TeamViewer = Annotated[AuthenticatedUser, Depends(require_permission(Permissions.TEAMS_VIEW))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
OrgTeamAdmin = Annotated[AuthenticatedUser, Depends(require_permission(Permissions.TEAMS_MANAGE))]
ScopedTeamAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_team_admin_or_permission(Permissions.TEAMS_MANAGE)),
]
ScopedProjectAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_team_admin_or_permission(Permissions.PROJECTS_MANAGE)),
]


@router.get("")
async def list_teams(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[TeamResponse]:
    teams = await facade.list_teams(scope=scope, db=db)
    if authorization_facade.has_permission(user, Permissions.TEAMS_VIEW):
        return teams
    allowed_scopes = authorization_facade.authorized_workspace_ids(user, relationship="member")
    return [team for team in teams if team.id in allowed_scopes.team_ids]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: CreateTeamRequest,
    actor: OrgTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> TeamResponse:
    try:
        return await facade.create_team(payload=payload, actor=actor, scope=scope, db=db)
    except TeamSlugAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="team slug already exists") from exc


@router.get("/{team_id}")
async def get_team(
    team_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> TeamResponse:
    try:
        team = await facade.get_team(team_id=team_id, scope=scope, db=db)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc
    if not authorization_facade.has_permission(user, Permissions.TEAMS_VIEW):
        await require_team_view_or_permission(
            team_id=str(team_id),
            permission="",
            user=user,
            db=db,
        )
    return team


@router.patch("/{team_id}")
async def update_team(
    team_id: UUID,
    payload: UpdateTeamRequest,
    actor: ScopedTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> TeamResponse:
    try:
        return await facade.update_team(
            team_id=team_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc
    except TeamSlugAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="team slug already exists") from exc


@router.get("/{team_id}/archive-impact")
async def get_team_archive_impact(
    team_id: UUID,
    actor: ScopedTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> TeamArchiveImpactResponse:
    try:
        return await workspace_facade.get_team_archive_impact(
            team_id=team_id,
            scope=scope,
            db=db,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_team(
    team_id: UUID,
    actor: ScopedTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await facade.deactivate_team(team_id=team_id, actor=actor, scope=scope, db=db)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


@router.get("/{team_id}/projects")
async def list_team_projects(
    team_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[ProjectResponse]:
    try:
        await require_team_view_or_permission(
            team_id=str(team_id),
            permission=Permissions.TEAMS_VIEW,
            user=user,
            db=db,
        )
        return await workspace_facade.list_team_projects(team_id=team_id, scope=scope, db=db)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


@router.get("/{team_id}/members")
async def list_team_members(
    team_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[TeamMemberResponse]:
    try:
        await require_team_view_or_permission(
            team_id=str(team_id),
            permission=Permissions.TEAMS_VIEW,
            user=user,
            db=db,
        )
        return await auth_facade.list_team_members(team_id=team_id, scope=scope, db=db)
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


@router.get("/{team_id}/member-options")
async def list_team_member_options(
    team_id: UUID,
    _: ScopedTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> list[MemberOptionResponse]:
    return await auth_facade.list_member_options(scope=scope, db=db)


@router.post("/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def add_team_member(
    team_id: UUID,
    payload: UpsertTeamMemberRequest,
    actor: ScopedTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> TeamMemberResponse:
    try:
        return await auth_facade.upsert_team_member(
            team_id=team_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="team or user not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.patch("/{team_id}/members/{user_id}")
async def update_team_member(
    team_id: UUID,
    user_id: UUID,
    payload: UpdateTeamMemberRequest,
    actor: ScopedTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> TeamMemberResponse:
    try:
        return await auth_facade.update_team_member(
            team_id=team_id,
            user_id=user_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="team member not found") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team member not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    actor: ScopedTeamAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> None:
    try:
        await auth_facade.remove_team_member(
            team_id=team_id,
            user_id=user_id,
            actor=actor,
            scope=scope,
            db=db,
        )
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="team member not found") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team member not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.get("/{team_id}/usage")
async def get_team_usage(
    team_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> OrganizationUsageSummary:
    try:
        await facade.get_team(team_id=team_id, scope=scope, db=db)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc
    await require_team_view_or_permission(
        team_id=str(team_id),
        permission=Permissions.TEAMS_VIEW,
        user=user,
        db=db,
    )
    return await usage_facade.get_organization_usage_summary(
        org_id=scope.org_id,
        team_id=team_id,
        window="30d",
        db=db,
    )


@router.post("/{team_id}/projects", status_code=status.HTTP_201_CREATED)
async def create_team_project(
    team_id: UUID,
    payload: CreateProjectRequest,
    actor: ScopedProjectAdmin,
    scope: RequestScope,
    db: DatabaseSession,
) -> ProjectResponse:
    try:
        return await workspace_facade.create_project(
            team_id=team_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc
    except TeamInactiveError as exc:
        raise HTTPException(
            status_code=409,
            detail="project cannot be created because the owning team is archived",
        ) from exc
    except ProjectSlugAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="project slug already exists") from exc
