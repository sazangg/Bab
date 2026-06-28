from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal import repository


async def count_active_virtual_keys_for_project_ids(
    *, org_id: UUID, project_ids: set[UUID], db: AsyncSession
) -> int:
    return await repository.count_active_virtual_keys_for_project_ids(
        org_id=org_id,
        project_ids=project_ids,
        db=db,
    )
