from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import Project, ProjectProviderAccess


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


async def grant_provider_access(
    *,
    org_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    allowed_models: list[str] | None,
    db: AsyncSession,
) -> ProjectProviderAccess:
    access = ProjectProviderAccess(
        org_id=org_id,
        project_id=project_id,
        provider_id=provider_id,
        allowed_models=allowed_models,
    )
    db.add(access)
    await db.flush()
    return access


async def list_provider_access(
    *,
    org_id: UUID,
    project_id: UUID,
    db: AsyncSession,
) -> list[ProjectProviderAccess]:
    result = await db.scalars(
        select(ProjectProviderAccess)
        .where(
            ProjectProviderAccess.org_id == org_id,
            ProjectProviderAccess.project_id == project_id,
        )
        .order_by(ProjectProviderAccess.created_at.desc())
    )
    return list(result)


async def get_provider_access(
    *,
    org_id: UUID,
    project_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> ProjectProviderAccess | None:
    return await db.scalar(
        select(ProjectProviderAccess).where(
            ProjectProviderAccess.org_id == org_id,
            ProjectProviderAccess.project_id == project_id,
            ProjectProviderAccess.provider_id == provider_id,
        )
    )


async def delete_provider_access(*, access: ProjectProviderAccess, db: AsyncSession) -> None:
    await db.delete(access)
    await db.flush()
