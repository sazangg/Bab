from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.workspace import service
from app.modules.workspace.actor import WorkspaceActor
from app.modules.workspace.internal import impact, projects, teams
from app.modules.workspace.schemas import (
    CreateProjectRequest,
    CreateTeamRequest,
    OrganizationIdentity,
    ProjectArchiveImpactResponse,
    ProjectMembershipTarget,
    ProjectOption,
    ProjectResponse,
    TeamArchiveImpactResponse,
    TeamMembershipTarget,
    TeamReadState,
    TeamResponse,
    UpdateProjectRequest,
    UpdateTeamRequest,
    ValidatedScope,
    WorkspaceAllowedScopeIds,
    WorkspaceFilterValidation,
    WorkspaceLabelMaps,
    WorkspaceProjectIdentity,
    WorkspaceProjectOption,
    WorkspaceTeamIdentity,
    WorkspaceVirtualKeyIdentity,
    WorkspaceVirtualKeyOption,
    WorkspaceVirtualKeyTarget,
)


async def validate_assignment_scope(
    *,
    organization_id: UUID,
    scope_type: str,
    db: AsyncSession,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
) -> ValidatedScope:
    return await service.validate_assignment_scope(
        organization_id=organization_id,
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )


async def lock_organization_scope_for_update(*, org_id: UUID, db: AsyncSession) -> None:
    await service.lock_organization_scope_for_update(org_id=org_id, db=db)


async def get_organization_identity(
    *, org_id: UUID, db: AsyncSession
) -> OrganizationIdentity | None:
    return await service.get_organization_identity(org_id=org_id, db=db)


async def update_organization_name(*, org_id: UUID, name: str, db: AsyncSession) -> None:
    await service.update_organization_name(org_id=org_id, name=name, db=db)


async def create_team(
    *,
    payload: CreateTeamRequest,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    return await teams.create_team(payload=payload, actor=actor, scope=scope, db=db)


async def list_teams(*, scope: Scope, db: AsyncSession) -> list[TeamResponse]:
    return await teams.list_teams(scope=scope, db=db)


async def get_team(*, team_id: UUID, scope: Scope, db: AsyncSession) -> TeamResponse:
    return await teams.get_team(team_id=team_id, scope=scope, db=db)


async def get_team_labels(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, str]:
    return await teams.get_team_labels(team_ids=team_ids, scope=scope, db=db)


async def get_team_read_states(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, TeamReadState]:
    return await teams.get_team_read_states(team_ids=team_ids, scope=scope, db=db)


async def get_team_membership_target(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> TeamMembershipTarget | None:
    return await teams.get_team_membership_target(team_id=team_id, scope=scope, db=db)


async def list_active_team_ids(*, scope: Scope, db: AsyncSession) -> set[UUID]:
    return await teams.list_active_team_ids(scope=scope, db=db)


async def ensure_team_active(*, team_id: UUID, scope: Scope, db: AsyncSession) -> TeamResponse:
    return await teams.ensure_team_active(team_id=team_id, scope=scope, db=db)


async def update_team(
    *,
    team_id: UUID,
    payload: UpdateTeamRequest,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> TeamResponse:
    return await teams.update_team(
        team_id=team_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_team(
    *,
    team_id: UUID,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await teams.deactivate_team(team_id=team_id, actor=actor, scope=scope, db=db)


async def create_project(
    *,
    team_id: UUID,
    payload: CreateProjectRequest,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    return await projects.create_project(
        team_id=team_id, payload=payload, actor=actor, scope=scope, db=db
    )


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    return await projects.list_projects(scope=scope, db=db)


async def get_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> ProjectResponse:
    return await projects.get_project(project_id=project_id, scope=scope, db=db)


async def get_project_membership_target(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectMembershipTarget | None:
    return await projects.get_project_membership_target(
        project_id=project_id, scope=scope, db=db
    )


async def get_project_team_ids(
    *, scope: Scope, project_ids: set[UUID] | None = None, db: AsyncSession
) -> dict[UUID, UUID]:
    return await projects.get_project_team_ids(scope=scope, project_ids=project_ids, db=db)


async def list_team_projects(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> list[ProjectResponse]:
    return await projects.list_team_projects(team_id=team_id, scope=scope, db=db)


async def get_team_archive_impact(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> TeamArchiveImpactResponse:
    return await impact.get_team_archive_impact(team_id=team_id, scope=scope, db=db)


async def update_project(
    *,
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: WorkspaceActor,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    return await projects.update_project(
        project_id=project_id, payload=payload, actor=actor, scope=scope, db=db
    )


async def deactivate_project(
    *, project_id: UUID, actor: WorkspaceActor, scope: Scope, db: AsyncSession
) -> None:
    await projects.deactivate_project(project_id=project_id, actor=actor, scope=scope, db=db)


async def get_project_labels(
    *, project_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, str]:
    return await projects.get_project_labels(project_ids=project_ids, scope=scope, db=db)


async def list_project_ids_for_team_ids(
    *, team_ids: set[UUID], scope: Scope, db: AsyncSession
) -> set[UUID]:
    return await projects.list_project_ids_for_team_ids(
        team_ids=team_ids, scope=scope, db=db
    )


async def list_project_options(
    *,
    scope: Scope,
    team_ids: set[UUID] | None,
    project_ids: set[UUID] | None,
    db: AsyncSession,
) -> list[ProjectOption]:
    return await projects.list_project_options(
        scope=scope, team_ids=team_ids, project_ids=project_ids, db=db
    )


async def get_project_archive_impact(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectArchiveImpactResponse:
    return await impact.get_project_archive_impact(project_id=project_id, scope=scope, db=db)


async def validate_filter_relationships(
    *,
    scope: Scope,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> WorkspaceFilterValidation:
    return await service.validate_filter_relationships(
        scope=scope,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
    )


async def expand_allowed_scope_ids(
    *,
    scope: Scope,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    db: AsyncSession,
) -> WorkspaceAllowedScopeIds | None:
    return await service.expand_allowed_scope_ids(
        scope=scope,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        db=db,
    )


async def get_workspace_label_maps(
    *,
    scope: Scope,
    team_ids: set[UUID],
    project_ids: set[UUID],
    virtual_key_ids: set[UUID],
    db: AsyncSession,
) -> WorkspaceLabelMaps:
    return await service.get_workspace_label_maps(
        scope=scope,
        team_ids=team_ids,
        project_ids=project_ids,
        virtual_key_ids=virtual_key_ids,
        db=db,
    )


async def list_workspace_projects(
    *,
    scope: Scope,
    team_ids: set[UUID] | None = None,
    project_ids: set[UUID] | None = None,
    include_all: bool = False,
    db: AsyncSession,
) -> list[WorkspaceProjectOption]:
    return await service.list_workspace_projects(
        scope=scope,
        team_ids=team_ids,
        project_ids=project_ids,
        include_all=include_all,
        db=db,
    )


async def list_workspace_virtual_keys(
    *,
    scope: Scope,
    project_ids: set[UUID] | None = None,
    virtual_key_ids: set[UUID] | None = None,
    usable_only: bool = True,
    db: AsyncSession,
) -> list[WorkspaceVirtualKeyOption]:
    return await service.list_workspace_virtual_keys(
        scope=scope,
        project_ids=project_ids,
        virtual_key_ids=virtual_key_ids,
        usable_only=usable_only,
        db=db,
    )


async def get_virtual_key_target(
    *, scope: Scope, virtual_key_id: UUID, db: AsyncSession
) -> WorkspaceVirtualKeyTarget | None:
    return await service.get_virtual_key_target(
        scope=scope,
        virtual_key_id=virtual_key_id,
        db=db,
    )


async def get_team_identity(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> WorkspaceTeamIdentity | None:
    return await service.get_team_identity(team_id=team_id, scope=scope, db=db)


async def get_project_identity(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> WorkspaceProjectIdentity | None:
    return await service.get_project_identity(project_id=project_id, scope=scope, db=db)


async def get_virtual_key_identity(
    *, virtual_key_id: UUID, scope: Scope, db: AsyncSession
) -> WorkspaceVirtualKeyIdentity | None:
    return await service.get_virtual_key_identity(
        virtual_key_id=virtual_key_id,
        scope=scope,
        db=db,
    )
