from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import OrganizationMembership, User
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
