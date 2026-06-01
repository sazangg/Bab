from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import Project, VirtualKey


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


async def create_virtual_key(
    *,
    org_id: UUID,
    project_id: UUID,
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
