from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Organization
from app.modules.workspace.errors import OrganizationInactiveError
from app.modules.workspace.internal.models import Project


async def get_organization(*, org_id: UUID, db: AsyncSession) -> Organization | None:
    return await db.scalar(select(Organization).where(Organization.id == org_id))


async def lock_organization_scope_for_update(*, org_id: UUID, db: AsyncSession) -> None:
    await db.execute(
        update(Organization).where(Organization.id == org_id).values(name=Organization.name)
    )
    await db.scalar(select(Organization).where(Organization.id == org_id).with_for_update())


async def ensure_organization_active(*, org_id: UUID, db: AsyncSession) -> None:
    organization = await get_organization(org_id=org_id, db=db)
    if organization is None or not organization.is_active:
        raise OrganizationInactiveError


async def create_project(
    *,
    org_id: UUID,
    team_id: UUID,
    created_by: UUID,
    name: str,
    slug: str,
    description: str | None,
    db: AsyncSession,
) -> Project:
    project = Project(
        org_id=org_id,
        team_id=team_id,
        created_by=created_by,
        name=name,
        slug=slug,
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


async def get_project_by_slug(
    *, org_id: UUID, team_id: UUID, slug: str, db: AsyncSession
) -> Project | None:
    return await db.scalar(
        select(Project).where(
            Project.org_id == org_id,
            Project.team_id == team_id,
            Project.slug == slug,
        )
    )


async def get_project_labels(
    *, org_id: UUID, project_ids: set[UUID], db: AsyncSession
) -> dict[UUID, str]:
    if not project_ids:
        return {}
    rows = (
        await db.execute(
            select(Project.id, Project.name).where(
                Project.org_id == org_id,
                Project.id.in_(project_ids),
            )
        )
    ).all()
    return {project_id: name for project_id, name in rows}


async def get_project_membership_target(
    *, org_id: UUID, project_id: UUID, db: AsyncSession
) -> tuple[UUID, UUID, UUID, str, bool] | None:
    return (
        await db.execute(
            select(Project.id, Project.org_id, Project.team_id, Project.name, Project.is_active)
            .where(Project.org_id == org_id, Project.id == project_id)
        )
    ).one_or_none()


async def get_project_team_ids(
    *, org_id: UUID, project_ids: set[UUID] | None, db: AsyncSession
) -> dict[UUID, UUID]:
    if project_ids is not None and not project_ids:
        return {}
    query = select(Project.id, Project.team_id).where(Project.org_id == org_id)
    if project_ids is not None:
        query = query.where(Project.id.in_(project_ids))
    rows = (await db.execute(query)).all()
    return {project_id: team_id for project_id, team_id in rows}


async def list_project_ids_for_team_ids(
    *, org_id: UUID, team_ids: set[UUID], db: AsyncSession
) -> set[UUID]:
    if not team_ids:
        return set()
    result = await db.scalars(
        select(Project.id).where(Project.org_id == org_id, Project.team_id.in_(team_ids))
    )
    return set(result)


async def list_project_options(
    *,
    org_id: UUID,
    team_ids: set[UUID] | None,
    project_ids: set[UUID] | None,
    db: AsyncSession,
) -> list[tuple[UUID, str, UUID]]:
    filters = [Project.org_id == org_id]
    if team_ids is not None:
        if not team_ids:
            return []
        filters.append(Project.team_id.in_(team_ids))
    if project_ids is not None:
        if not project_ids:
            return []
        filters.append(Project.id.in_(project_ids))
    rows = (
        await db.execute(
            select(Project.id, Project.name, Project.team_id)
            .where(*filters)
            .order_by(Project.name)
        )
    ).all()
    return list(rows)


async def count_active_team_projects(*, org_id: UUID, team_id: UUID, db: AsyncSession) -> int:
    count = await db.scalar(
        select(func.count(Project.id)).where(
            Project.org_id == org_id,
            Project.team_id == team_id,
            Project.is_active.is_(True),
        )
    )
    return int(count or 0)
