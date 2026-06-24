from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policy_kernel import repository
from app.modules.policy_kernel.models import PolicyRevision


async def create_initial_active_revision(
    *,
    org_id: UUID,
    policy_id: UUID,
    created_by: UUID | None,
    db: AsyncSession,
) -> PolicyRevision:
    return await repository.create_policy_revision(
        org_id=org_id,
        policy_id=policy_id,
        revision_number=1,
        status="active",
        created_by=created_by,
        db=db,
    )


async def create_next_active_revision(
    *,
    org_id: UUID,
    policy_id: UUID,
    created_by: UUID | None,
    db: AsyncSession,
) -> PolicyRevision:
    active_revision = await repository.archive_active_policy_revision(
        org_id=org_id,
        policy_id=policy_id,
        db=db,
    )
    next_revision_number = 1 if active_revision is None else active_revision.revision_number + 1
    return await repository.create_policy_revision(
        org_id=org_id,
        policy_id=policy_id,
        revision_number=next_revision_number,
        status="active",
        created_by=created_by,
        db=db,
    )
