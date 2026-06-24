from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.keys.internal import repository
from app.modules.keys.schemas import ProjectMembershipTarget


async def get_project_membership_target(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectMembershipTarget | None:
    row = await repository.get_project_membership_target(
        org_id=scope.org_id,
        project_id=project_id,
        db=db,
    )
    if row is None:
        return None
    project_id, org_id, team_id, name, is_active = row
    return ProjectMembershipTarget(
        id=project_id,
        org_id=org_id,
        team_id=team_id,
        name=name,
        is_active=is_active,
    )


async def get_project_team_ids(
    *, scope: Scope, project_ids: set[UUID] | None = None, db: AsyncSession
) -> dict[UUID, UUID]:
    return await repository.get_project_team_ids(
        org_id=scope.org_id,
        project_ids=project_ids,
        db=db,
    )
