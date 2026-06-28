from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Organization
from app.modules.workspace.errors import OrganizationInactiveError
from app.modules.workspace.internal.models import Project, Team


@dataclass(frozen=True)
class WorkspaceOrganizationRuntimeState:
    id: UUID
    is_active: bool


@dataclass(frozen=True)
class WorkspaceProjectRuntimeState:
    id: UUID
    org_id: UUID
    team_id: UUID
    name: str
    is_active: bool
    team_name: str | None
    team_is_active: bool
    organization_is_active: bool


async def get_organization_runtime_state(
    *, org_id: UUID, db: AsyncSession
) -> WorkspaceOrganizationRuntimeState | None:
    row = (
        await db.execute(
            select(Organization.id, Organization.is_active).where(Organization.id == org_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return WorkspaceOrganizationRuntimeState(id=row.id, is_active=row.is_active)


async def ensure_organization_active(*, org_id: UUID, db: AsyncSession) -> None:
    organization = await get_organization_runtime_state(org_id=org_id, db=db)
    if organization is None or not organization.is_active:
        raise OrganizationInactiveError


async def get_project_runtime_state(
    *, org_id: UUID, project_id: UUID, db: AsyncSession
) -> WorkspaceProjectRuntimeState | None:
    states = await get_project_runtime_states(org_id=org_id, project_ids={project_id}, db=db)
    return states.get(project_id)


async def get_project_runtime_states(
    *, org_id: UUID, project_ids: set[UUID], db: AsyncSession
) -> dict[UUID, WorkspaceProjectRuntimeState]:
    if not project_ids:
        return {}
    rows = (
        await db.execute(
            select(
                Project.id,
                Project.org_id,
                Project.team_id,
                Project.name,
                Project.is_active,
                Team.name.label("team_name"),
                Team.is_active.label("team_is_active"),
                Organization.is_active.label("organization_is_active"),
            )
            .join(Team, Team.id == Project.team_id)
            .join(Organization, Organization.id == Project.org_id)
            .where(Project.org_id == org_id, Project.id.in_(project_ids))
        )
    ).all()
    return {
        row.id: WorkspaceProjectRuntimeState(
            id=row.id,
            org_id=row.org_id,
            team_id=row.team_id,
            name=row.name,
            is_active=row.is_active,
            team_name=row.team_name,
            team_is_active=row.team_is_active,
            organization_is_active=row.organization_is_active,
        )
        for row in rows
    }


async def list_project_ids_for_hierarchy_filter(
    *,
    org_id: UUID,
    visible_team_ids: set[UUID] | None,
    visible_project_ids: set[UUID] | None,
    team_id: UUID | None,
    project_id: UUID | None,
    project_active: bool | None = None,
    team_active: bool | None = None,
    db: AsyncSession,
) -> set[UUID]:
    filters = [Project.org_id == org_id]
    if visible_team_ids is not None and visible_project_ids is not None:
        visibility = []
        if visible_team_ids:
            visibility.append(Project.team_id.in_(visible_team_ids))
        if visible_project_ids:
            visibility.append(Project.id.in_(visible_project_ids))
        if not visibility:
            return set()
        filters.append(visibility[0] if len(visibility) == 1 else visibility[0] | visibility[1])
    if team_id is not None:
        filters.append(Project.team_id == team_id)
    if project_id is not None:
        filters.append(Project.id == project_id)
    if project_active is not None:
        filters.append(Project.is_active.is_(project_active))
    query = select(Project.id).where(*filters)
    if team_active is not None:
        query = query.join(Team, Team.id == Project.team_id).where(
            Team.is_active.is_(team_active)
        )
    result = await db.scalars(query)
    return set(result)


async def list_project_ids_for_team(
    *, org_id: UUID, team_id: UUID, active_only: bool, db: AsyncSession
) -> set[UUID]:
    filters = [Project.org_id == org_id, Project.team_id == team_id]
    if active_only:
        filters.append(Project.is_active.is_(True))
    result = await db.scalars(select(Project.id).where(*filters))
    return set(result)
