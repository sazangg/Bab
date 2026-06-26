from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import (
    OrganizationMembership,
    ProjectMembership,
    TeamMembership,
    User,
)
from app.modules.auth.schemas import UserLabel


async def get_user_labels(
    *, org_id: UUID, user_ids: set[UUID], db: AsyncSession
) -> dict[UUID, UserLabel]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.name, User.email)
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .where(
                OrganizationMembership.org_id == org_id,
                User.id.in_(user_ids),
            )
        )
    ).all()
    return {
        user_id: UserLabel(id=user_id, display_name=name, email=email)
        for user_id, name, email in rows
    }


async def count_team_members_by_role(
    *,
    org_id: UUID,
    team_id: UUID,
    db: AsyncSession,
) -> tuple[int, int]:
    rows = (
        await db.execute(
            select(TeamMembership.role, func.count(TeamMembership.id))
            .where(TeamMembership.org_id == org_id, TeamMembership.team_id == team_id)
            .group_by(TeamMembership.role)
        )
    ).all()
    counts = {role: int(count) for role, count in rows}
    return counts.get("team_admin", 0), counts.get("team_member", 0)


async def count_project_admins(*, org_id: UUID, project_id: UUID, db: AsyncSession) -> int:
    count = await db.scalar(
        select(func.count(ProjectMembership.id)).where(
            ProjectMembership.org_id == org_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.role == "project_admin",
        )
    )
    return int(count or 0)
