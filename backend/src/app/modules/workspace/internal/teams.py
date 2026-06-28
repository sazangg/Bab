import re
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.workspace.actor import WorkspaceActor
from app.modules.workspace.errors import (
    TeamInactiveError,
    TeamNotFoundError,
    TeamSlugAlreadyExistsError,
)
from app.modules.workspace.internal import repository
from app.modules.workspace.internal.models import Team
from app.modules.workspace.schemas import (
    CreateTeamRequest,
    TeamIdentity,
    TeamMembershipTarget,
    TeamReadState,
    TeamResponse,
    UpdateTeamRequest,
)

logger = structlog.get_logger(__name__)


async def create_team(
    *,
    payload: CreateTeamRequest,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    slug = _slugify(payload.slug or payload.name)
    async with transaction(db):
        await _ensure_slug_available(slug=slug, scope=scope, db=db)
        try:
            team = await repository.create_team(
                org_id=scope.org_id,
                name=payload.name,
                slug=slug,
                description=payload.description,
                db=db,
            )
        except IntegrityError as exc:
            raise TeamSlugAlreadyExistsError from exc
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="team.created",
            message=f"Created team {team.name}.",
            team_id=team.id,
            metadata={"team_id": str(team.id)},
            db=db,
        )

    logger.info(
        "team_created",
        team_id=str(team.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return TeamResponse.model_validate(team)


async def list_teams(*, scope: Scope, db: AsyncSession) -> list[TeamResponse]:
    teams = await repository.list_teams(org_id=scope.org_id, db=db)
    return [TeamResponse.model_validate(team) for team in teams]


async def get_team(*, team_id: UUID, scope: Scope, db: AsyncSession) -> TeamResponse:
    team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
    return TeamResponse.model_validate(team)


async def get_team_identity(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> TeamIdentity | None:
    team = await repository.get_team(org_id=scope.org_id, team_id=team_id, db=db)
    if team is None:
        return None
    return TeamIdentity(id=team.id, org_id=team.org_id, is_active=team.is_active)


async def get_team_labels(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, str]:
    return await repository.get_team_labels(org_id=scope.org_id, team_ids=team_ids, db=db)


async def get_team_read_states(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, TeamReadState]:
    rows = await repository.get_team_read_states(
        org_id=scope.org_id,
        team_ids=team_ids,
        db=db,
    )
    return {
        team_id: TeamReadState(id=team_id, name=name, is_active=is_active)
        for team_id, (name, is_active) in rows.items()
    }


async def get_team_membership_target(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> TeamMembershipTarget | None:
    row = await repository.get_team_membership_target(
        org_id=scope.org_id,
        team_id=team_id,
        db=db,
    )
    if row is None:
        return None
    team_id, org_id, name, is_active = row
    return TeamMembershipTarget(
        id=team_id,
        org_id=org_id,
        name=name,
        is_active=is_active,
    )


async def list_active_team_ids(*, scope: Scope, db: AsyncSession) -> set[UUID]:
    return await repository.list_active_team_ids(org_id=scope.org_id, db=db)


async def ensure_team_active(*, team_id: UUID, scope: Scope, db: AsyncSession) -> TeamResponse:
    team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
    if not team.is_active:
        raise TeamInactiveError
    return TeamResponse.model_validate(team)


async def update_team(
    *,
    team_id: UUID,
    payload: UpdateTeamRequest,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    async with transaction(db):
        team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
        changed_fields: dict[str, dict[str, object]] = {}
        if payload.slug is not None:
            slug = _slugify(payload.slug)
            if slug != team.slug:
                await _ensure_slug_available(slug=slug, scope=scope, db=db)
                changed_fields["slug"] = {"from": team.slug, "to": slug}
                team.slug = slug
        if payload.name is not None:
            if payload.name != team.name:
                changed_fields["name"] = {"from": team.name, "to": payload.name}
            team.name = payload.name
        if "description" in payload.model_fields_set:
            if payload.description != team.description:
                changed_fields["description"] = {
                    "from": team.description,
                    "to": payload.description,
                }
            team.description = payload.description
        if payload.is_active is not None:
            if payload.is_active != team.is_active:
                changed_fields["is_active"] = {"from": team.is_active, "to": payload.is_active}
            team.is_active = payload.is_active
        try:
            await db.flush()
        except IntegrityError as exc:
            raise TeamSlugAlreadyExistsError from exc
        action = (
            "team.reactivated"
            if changed_fields.get("is_active", {}).get("to") is True
            else "team.deactivated"
            if changed_fields.get("is_active", {}).get("to") is False
            else "team.updated"
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action=action,
            message=f"Updated team {team.name}.",
            team_id=team.id,
            metadata={"team_id": str(team.id), "changed_fields": changed_fields},
            db=db,
        )

    logger.info(
        "team_updated",
        team_id=str(team.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return TeamResponse.model_validate(team)


async def deactivate_team(
    *,
    team_id: UUID,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        team = await _get_team_or_raise(team_id=team_id, scope=scope, db=db)
        team.is_active = False
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="workspace",
            action="team.deactivated",
            message=f"Deactivated team {team.name}.",
            team_id=team.id,
            metadata={"team_id": str(team.id)},
            db=db,
        )

    logger.info(
        "team_deactivated",
        team_id=str(team_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )


async def _get_team_or_raise(*, team_id: UUID, scope: Scope, db: AsyncSession) -> Team:
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
