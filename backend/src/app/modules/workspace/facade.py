from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.workspace import service
from app.modules.workspace.schemas import (
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


async def require_assignment_admin(
    *,
    actor: AuthenticatedUser,
    scope: Scope,
    scope_type: str,
    db: AsyncSession,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    global_permissions: set[str] | None = None,
) -> None:
    await service.require_assignment_admin(
        actor=actor,
        scope=scope,
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        global_permissions=global_permissions,
        db=db,
    )


async def can_manage_assignment_scope(
    *,
    actor: AuthenticatedUser,
    scope: Scope,
    scope_type: str,
    db: AsyncSession,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
) -> bool:
    return await service.can_manage_assignment_scope(
        actor=actor,
        scope=scope,
        scope_type=scope_type,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        db=db,
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


def managed_scope_ids(actor: AuthenticatedUser) -> tuple[set[UUID], set[UUID]]:
    return service.managed_scope_ids(actor)


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


async def has_team_membership(
    *, team_id: UUID, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    return await service.has_team_membership(team_id=team_id, actor=actor, db=db)


async def is_team_admin(*, team_id: UUID, actor: AuthenticatedUser, db: AsyncSession) -> bool:
    return await service.is_team_admin(team_id=team_id, actor=actor, db=db)


async def has_project_membership(
    *, project_id: UUID, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    return await service.has_project_membership(project_id=project_id, actor=actor, db=db)


async def is_project_admin(
    *, project_id: UUID, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    return await service.is_project_admin(project_id=project_id, actor=actor, db=db)
