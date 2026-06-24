from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.teams.internal import service
from app.modules.teams.schemas import (
    CreateTeamRequest,
    TeamIdentity,
    TeamReadState,
    TeamResponse,
    UpdateTeamRequest,
)


async def create_team(
    *,
    payload: CreateTeamRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    return await service.create_team(payload=payload, actor=actor, scope=scope, db=db)


async def list_teams(*, scope: Scope, db: AsyncSession) -> list[TeamResponse]:
    return await service.list_teams(scope=scope, db=db)


async def get_team(*, team_id: UUID, scope: Scope, db: AsyncSession) -> TeamResponse:
    return await service.get_team(team_id=team_id, scope=scope, db=db)


async def get_team_identity(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> TeamIdentity | None:
    return await service.get_team_identity(team_id=team_id, scope=scope, db=db)


async def get_team_labels(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, str]:
    return await service.get_team_labels(team_ids=team_ids, scope=scope, db=db)


async def get_team_read_states(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, TeamReadState]:
    return await service.get_team_read_states(team_ids=team_ids, scope=scope, db=db)


async def list_active_team_ids(*, scope: Scope, db: AsyncSession) -> set[UUID]:
    return await service.list_active_team_ids(scope=scope, db=db)


async def ensure_team_active(*, team_id: UUID, scope: Scope, db: AsyncSession) -> TeamResponse:
    return await service.ensure_team_active(team_id=team_id, scope=scope, db=db)


async def update_team(
    *,
    team_id: UUID,
    payload: UpdateTeamRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    return await service.update_team(
        team_id=team_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_team(
    *,
    team_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_team(team_id=team_id, actor=actor, scope=scope, db=db)
