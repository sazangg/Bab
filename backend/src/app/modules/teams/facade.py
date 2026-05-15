from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.teams.internal import service
from app.modules.teams.schemas import CreateTeamRequest, TeamResponse, UpdateTeamRequest


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
