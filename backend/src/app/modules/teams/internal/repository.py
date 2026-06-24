from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Team


async def create_team(
    *,
    org_id: UUID,
    name: str,
    slug: str,
    description: str | None,
    db: AsyncSession,
) -> Team:
    team = Team(org_id=org_id, name=name, slug=slug, description=description)
    db.add(team)
    await db.flush()
    return team


async def list_teams(*, org_id: UUID, db: AsyncSession) -> list[Team]:
    result = await db.scalars(select(Team).where(Team.org_id == org_id).order_by(Team.name))
    return list(result)


async def get_team(*, org_id: UUID, team_id: UUID, db: AsyncSession) -> Team | None:
    return await db.scalar(select(Team).where(Team.org_id == org_id, Team.id == team_id))


async def get_team_by_slug(*, org_id: UUID, slug: str, db: AsyncSession) -> Team | None:
    return await db.scalar(select(Team).where(Team.org_id == org_id, Team.slug == slug))


async def get_team_labels(
    *, org_id: UUID, team_ids: set[UUID], db: AsyncSession
) -> dict[UUID, str]:
    if not team_ids:
        return {}
    rows = (
        await db.execute(
            select(Team.id, Team.name).where(Team.org_id == org_id, Team.id.in_(team_ids))
        )
    ).all()
    return {team_id: name for team_id, name in rows}


async def get_team_read_states(
    *, org_id: UUID, team_ids: set[UUID], db: AsyncSession
) -> dict[UUID, tuple[str, bool]]:
    if not team_ids:
        return {}
    rows = (
        await db.execute(
            select(Team.id, Team.name, Team.is_active).where(
                Team.org_id == org_id,
                Team.id.in_(team_ids),
            )
        )
    ).all()
    return {team_id: (name, is_active) for team_id, name, is_active in rows}


async def list_active_team_ids(*, org_id: UUID, db: AsyncSession) -> set[UUID]:
    result = await db.scalars(
        select(Team.id).where(Team.org_id == org_id, Team.is_active.is_(True))
    )
    return set(result)
