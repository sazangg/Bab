from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import Project


async def create_project(
    *,
    org_id: UUID,
    created_by: UUID,
    name: str,
    description: str | None,
    db: AsyncSession,
) -> Project:
    project = Project(org_id=org_id, created_by=created_by, name=name, description=description)
    db.add(project)
    await db.flush()
    return project


async def list_projects(*, org_id: UUID, db: AsyncSession) -> list[Project]:
    result = await db.scalars(
        select(Project).where(Project.org_id == org_id).order_by(Project.name)
    )
    return list(result)


async def get_project(*, project_id: UUID, org_id: UUID, db: AsyncSession) -> Project | None:
    return await db.scalar(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
