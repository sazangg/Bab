from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope, get_db
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as projects_facade
from app.modules.keys.schemas import AllocationResponse, CreateProjectRequest, ProjectResponse
from app.modules.teams import facade
from app.modules.teams.errors import TeamNotFoundError, TeamSlugAlreadyExistsError
from app.modules.teams.schemas import CreateTeamRequest, TeamResponse, UpdateTeamRequest
from app.modules.usage import facade as usage_facade
from app.modules.usage.schemas import AllocationUsageSummary

router = APIRouter(prefix="/teams", tags=["teams"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RequestScope = Annotated[Scope, Depends(get_scope)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
TeamAdmin = Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]


@router.get("")
async def list_teams(
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[TeamResponse]:
    return await facade.list_teams(scope=scope, db=db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: CreateTeamRequest,
    actor: TeamAdmin,
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
    _: CurrentUser,
) -> TeamResponse:
    try:
        return await facade.get_team(team_id=team_id, scope=scope, db=db)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


@router.patch("/{team_id}")
async def update_team(
    team_id: UUID,
    payload: UpdateTeamRequest,
    actor: TeamAdmin,
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
    actor: TeamAdmin,
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
    _: CurrentUser,
) -> list[ProjectResponse]:
    try:
        return await projects_facade.list_team_projects(team_id=team_id, scope=scope, db=db)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


@router.get("/{team_id}/allocations")
async def list_team_allocations(
    team_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[AllocationResponse]:
    try:
        return await projects_facade.list_team_allocations(team_id=team_id, scope=scope, db=db)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc


@router.get("/{team_id}/allocations/usage")
async def list_team_allocation_usage(
    team_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    _: CurrentUser,
) -> list[AllocationUsageSummary]:
    try:
        allocations = await projects_facade.list_team_allocations(
            team_id=team_id, scope=scope, db=db
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail="team not found") from exc
    return [
        await usage_facade.get_allocation_usage_summary(
            allocation_id=allocation.id,
            org_id=scope.org_id,
            db=db,
        )
        for allocation in allocations
    ]


@router.post("/{team_id}/projects", status_code=status.HTTP_201_CREATED)
async def create_team_project(
    team_id: UUID,
    payload: CreateProjectRequest,
    actor: TeamAdmin,
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
