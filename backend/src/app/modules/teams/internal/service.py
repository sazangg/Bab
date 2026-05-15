import re
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.teams.errors import TeamNotFoundError, TeamSlugAlreadyExistsError
from app.modules.teams.internal import repository
from app.modules.teams.schemas import CreateTeamRequest, TeamResponse, UpdateTeamRequest

logger = structlog.get_logger(__name__)


async def create_team(
    *,
    payload: CreateTeamRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    slug = _slugify(payload.slug or payload.name)
    async with transaction(db):
        await _ensure_slug_available(slug=slug, scope=scope, db=db)
        team = await repository.create_team(
            org_id=scope.org_id,
            name=payload.name,
            slug=slug,
            description=payload.description,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="team.created",
                target_type="team",
                target_id=team.id,
                event_metadata={"name": team.name, "slug": team.slug},
            ),
            db,
        )

    logger.info("team_created", team_id=str(team.id), org_id=str(scope.org_id))
    return TeamResponse.model_validate(team)


async def list_teams(*, scope: Scope, db: AsyncSession) -> list[TeamResponse]:
    teams = await repository.list_teams(org_id=scope.org_id, db=db)
    return [TeamResponse.model_validate(team) for team in teams]


async def get_team(*, team_id: UUID, scope: Scope, db: AsyncSession) -> TeamResponse:
    team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
    return TeamResponse.model_validate(team)


async def update_team(
    *,
    team_id: UUID,
    payload: UpdateTeamRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    async with transaction(db):
        team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
        if payload.slug is not None:
            slug = _slugify(payload.slug)
            if slug != team.slug:
                await _ensure_slug_available(slug=slug, scope=scope, db=db)
                team.slug = slug
        if payload.name is not None:
            team.name = payload.name
        if "description" in payload.model_fields_set:
            team.description = payload.description
        if payload.is_active is not None:
            team.is_active = payload.is_active
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="team.updated",
                target_type="team",
                target_id=team.id,
            ),
            db,
        )

    logger.info("team_updated", team_id=str(team.id), org_id=str(scope.org_id))
    return TeamResponse.model_validate(team)


async def deactivate_team(
    *,
    team_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
        team.is_active = False
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="team.deactivated",
                target_type="team",
                target_id=team.id,
            ),
            db,
        )

    logger.info("team_deactivated", team_id=str(team_id), org_id=str(scope.org_id))


async def _get_team_or_raise(*, team_id: UUID, scope: Scope, db: AsyncSession):
    team = await repository.get_team(org_id=scope.org_id, team_id=team_id, db=db)
    if team is None:
        raise TeamNotFoundError
    return team


async def _ensure_slug_available(*, slug: str, scope: Scope, db: AsyncSession) -> None:
    existing = await repository.get_team_by_slug(org_id=scope.org_id, slug=slug, db=db)
    if existing is not None:
        raise TeamSlugAlreadyExistsError


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "team"
