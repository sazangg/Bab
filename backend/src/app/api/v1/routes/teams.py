from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    accessible_team_ids,
    get_current_user,
    get_scope,
    require_permission,
    require_team_admin_or_permission,
    require_team_view_or_permission,
)
from app.core.database import Scope, get_db
from app.modules.auth import facade as auth_facade
from app.modules.auth.errors import InvalidAccessTokenError
from app.modules.auth.schemas import (
    AuthenticatedUser,
    TeamMemberResponse,
    UpdateTeamMemberRequest,
    UpsertTeamMemberRequest,
)
from app.modules.keys import facade as projects_facade
from app.modules.keys.schemas import CreateProjectRequest, ProjectResponse
from app.modules.teams import facade
from app.modules.teams.errors import TeamNotFoundError, TeamSlugAlreadyExistsError
from app.modules.teams.schemas import CreateTeamRequest, TeamResponse, UpdateTeamRequest
from app.modules.usage import facade as usage_facade
from app.modules.usage.schemas import OrganizationUsageSummary

router = APIRouter(prefix="/teams", tags=["teams"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
TeamViewer = Annotated[AuthenticatedUser, Depends(require_permission("teams.view"))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
OrgTeamAdmin = Annotated[AuthenticatedUser, Depends(require_permission("teams.manage"))]
ScopedTeamAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_team_admin_or_permission("teams.manage")),
]
ScopedProjectAdmin = Annotated[
    AuthenticatedUser,
    Depends(require_team_admin_or_permission("projects.manage")),
]


@router.get("")
async def list_teams(
    scope: RequestScope,
    db: DatabaseSession,
    user: CurrentUser,
) -> list[TeamResponse]:
    teams = await facade.list_teams(scope=scope, db=db)
    if auth_facade.has_permission(user, "teams.view"):
        return teams
    allowed_ids = accessible_team_ids(user)
    return [team for team in teams if team.id in allowed_ids]


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
    await require_team_view_or_permission(
        team_id=str(team_id),
        permission="teams.view",
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
            permission="teams.view",
            user=user,
            db=db,
        )
        return await projects_facade.list_team_projects(team_id=team_id, scope=scope, db=db)
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
            permission="teams.view",
            user=user,
            db=db,
        )
        return await auth_facade.list_team_members(team_id=team_id, scope=scope, db=db)
    except InvalidAccessTokenError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


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
        permission="teams.view",
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
        return await projects_facade.create_project(
            team_id=team_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc
