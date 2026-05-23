from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import Allocation, Project, VirtualKey


async def create_project(
    *,
    org_id: UUID,
    team_id: UUID,
    created_by: UUID,
    name: str,
    description: str | None,
    db: AsyncSession,
) -> Project:
    project = Project(
        org_id=org_id,
        team_id=team_id,
        created_by=created_by,
        name=name,
        description=description,
    )
    db.add(project)
    await db.flush()
    return project


async def list_projects(*, org_id: UUID, db: AsyncSession) -> list[Project]:
    result = await db.scalars(
        select(Project).where(Project.org_id == org_id).order_by(Project.name)
    )
    return list(result)


async def list_team_projects(*, org_id: UUID, team_id: UUID, db: AsyncSession) -> list[Project]:
    result = await db.scalars(
        select(Project)
        .where(Project.org_id == org_id, Project.team_id == team_id)
        .order_by(Project.name)
    )
    return list(result)


async def get_project(*, project_id: UUID, org_id: UUID, db: AsyncSession) -> Project | None:
    return await db.scalar(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )


async def create_allocation(
    *,
    org_id: UUID,
    parent_allocation_id: UUID | None,
    target_type: str,
    team_id: UUID | None,
    project_id: UUID | None,
    name: str,
    description: str | None,
    offerings: list[dict[str, str]],
    is_default: bool,
    budget_cents: int | None,
    max_requests: int | None,
    max_input_tokens: int | None,
    max_output_tokens: int | None,
    max_tokens_per_request: int | None,
    window: str,
    db: AsyncSession,
) -> Allocation:
    allocation = Allocation(
        org_id=org_id,
        parent_allocation_id=parent_allocation_id,
        target_type=target_type,
        team_id=team_id,
        project_id=project_id,
        name=name,
        description=description,
        offerings=offerings,
        is_default=is_default,
        budget_cents=budget_cents,
        max_requests=max_requests,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_tokens_per_request=max_tokens_per_request,
        window=window,
    )
    db.add(allocation)
    await db.flush()
    return allocation


async def list_allocations(*, org_id: UUID, db: AsyncSession) -> list[Allocation]:
    result = await db.scalars(
        select(Allocation).where(Allocation.org_id == org_id).order_by(Allocation.created_at.desc())
    )
    return list(result)


async def list_team_allocations(
    *,
    org_id: UUID,
    team_id: UUID,
    db: AsyncSession,
) -> list[Allocation]:
    result = await db.scalars(
        select(Allocation)
        .where(Allocation.org_id == org_id, Allocation.team_id == team_id)
        .order_by(Allocation.created_at.desc())
    )
    return list(result)


async def list_project_allocations(
    *,
    org_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[Allocation]:
    result = await db.scalars(
        select(Allocation)
        .where(Allocation.org_id == org_id, Allocation.project_id == project_id)
        .order_by(Allocation.created_at.desc())
    )
    return list(result)


async def get_allocation(
    *,
    allocation_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> Allocation | None:
    return await db.scalar(
        select(Allocation).where(Allocation.id == allocation_id, Allocation.org_id == org_id)
    )


async def get_parent_allocations(
    *,
    allocation: Allocation,
    org_id: UUID,
    db: AsyncSession,
) -> list[Allocation]:
    parents: list[Allocation] = []
    parent_id = allocation.parent_allocation_id
    seen_ids = {allocation.id}
    while parent_id is not None and parent_id not in seen_ids:
        parent = await get_allocation(allocation_id=parent_id, org_id=org_id, db=db)
        if parent is None:
            break
        parents.append(parent)
        seen_ids.add(parent.id)
        parent_id = parent.parent_allocation_id
    return parents


async def get_default_team_allocation(
    *,
    org_id: UUID,
    team_id: UUID,
    db: AsyncSession,
) -> Allocation | None:
    return await db.scalar(
        select(Allocation).where(
            Allocation.org_id == org_id,
            Allocation.team_id == team_id,
            Allocation.project_id.is_(None),
            Allocation.is_default.is_(True),
            Allocation.is_active.is_(True),
        )
    )


async def get_default_project_allocation(
    *,
    org_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> Allocation | None:
    return await db.scalar(
        select(Allocation).where(
            Allocation.org_id == org_id,
            Allocation.project_id == project_id,
            Allocation.is_default.is_(True),
            Allocation.is_active.is_(True),
        )
    )


async def clear_default_allocations(
    *,
    org_id: UUID,
    team_id: UUID | None,
    project_id: UUID | None,
    db: AsyncSession,
) -> None:
    result = await db.scalars(
        select(Allocation).where(
            Allocation.org_id == org_id,
            Allocation.team_id == team_id,
            Allocation.project_id == project_id,
            Allocation.is_default.is_(True),
        )
    )
    for allocation in result:
        allocation.is_default = False


async def create_virtual_key(
    *,
    org_id: UUID,
    project_id: UUID,
    allocation_id: UUID,
    custom_allocation_id: UUID | None,
    name: str,
    key_hash: str,
    key_prefix: str,
    allowed_models: list[str] | None,
    expires_at,
    db: AsyncSession,
) -> VirtualKey:
    virtual_key = VirtualKey(
        org_id=org_id,
        project_id=project_id,
        allocation_id=allocation_id,
        custom_allocation_id=custom_allocation_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        allowed_models=allowed_models,
        expires_at=expires_at,
    )
    db.add(virtual_key)
    await db.flush()
    return virtual_key


async def list_virtual_keys(
    *,
    org_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[VirtualKey]:
    result = await db.scalars(
        select(VirtualKey)
        .where(VirtualKey.org_id == org_id, VirtualKey.project_id == project_id)
        .order_by(VirtualKey.created_at.desc())
    )
    return list(result)


async def get_virtual_key(
    *,
    org_id: UUID,
    project_id: UUID,
    key_id: UUID,
    db: AsyncSession,
) -> VirtualKey | None:
    return await db.scalar(
        select(VirtualKey).where(
            VirtualKey.org_id == org_id,
            VirtualKey.project_id == project_id,
            VirtualKey.id == key_id,
        )
    )


async def get_virtual_key_by_hash(*, key_hash: str, db: AsyncSession) -> VirtualKey | None:
    return await db.scalar(select(VirtualKey).where(VirtualKey.key_hash == key_hash))
