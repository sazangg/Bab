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
