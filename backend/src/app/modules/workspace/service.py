from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth import facade as auth_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as keys_runtime_facade
from app.modules.teams import facade as teams_facade
from app.modules.workspace.errors import WorkspaceScopeNotFoundError
from app.modules.workspace.internal import projects
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


async def validate_assignment_scope(
    *,
    organization_id: UUID,
    scope_type: str,
    db: AsyncSession,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
) -> ValidatedScope:
    scope = Scope(org_id=organization_id)
    if scope_type == "org":
        if team_id is not None or project_id is not None or virtual_key_id is not None:
            raise WorkspaceScopeNotFoundError("invalid")
        return ValidatedScope(scope_type="org")
    if scope_type == "team":
        if team_id is None or project_id is not None or virtual_key_id is not None:
            raise WorkspaceScopeNotFoundError("invalid")
        team = await get_team_identity(team_id=team_id, scope=scope, db=db)
        if team is None:
            raise WorkspaceScopeNotFoundError
        return ValidatedScope(scope_type="team", team_id=team_id)
    if scope_type == "project":
        if project_id is None or virtual_key_id is not None:
            raise WorkspaceScopeNotFoundError("invalid")
        project = await get_project_identity(project_id=project_id, scope=scope, db=db)
        if project is None:
            raise WorkspaceScopeNotFoundError
        if team_id is not None and team_id != project.team_id:
            raise WorkspaceScopeNotFoundError("invalid")
        return ValidatedScope(scope_type="project", project_id=project_id)
    if scope_type == "virtual_key":
        if virtual_key_id is None:
            raise WorkspaceScopeNotFoundError("invalid")
        virtual_key = await get_virtual_key_identity(
            virtual_key_id=virtual_key_id,
            scope=scope,
            db=db,
        )
        if virtual_key is None:
            raise WorkspaceScopeNotFoundError
        project = await get_project_identity(project_id=virtual_key.project_id, scope=scope, db=db)
        if project is None:
            raise WorkspaceScopeNotFoundError
        if project_id is not None and project_id != virtual_key.project_id:
            raise WorkspaceScopeNotFoundError("invalid")
        if team_id is not None and team_id != project.team_id:
            raise WorkspaceScopeNotFoundError("invalid")
        return ValidatedScope(scope_type="virtual_key", virtual_key_id=virtual_key_id)
    raise WorkspaceScopeNotFoundError("invalid")


async def validate_filter_relationships(
    *,
    scope: Scope,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    db: AsyncSession,
) -> WorkspaceFilterValidation:
    project: WorkspaceProjectIdentity | None = None
    if project_id is not None:
        project = await get_project_identity(project_id=project_id, scope=scope, db=db)
        if project is None:
            raise WorkspaceScopeNotFoundError("not_found")
        if team_id is not None and project.team_id != team_id:
            raise WorkspaceScopeNotFoundError("project_team_mismatch")
    if virtual_key_id is not None:
        virtual_key = await get_virtual_key_identity(
            virtual_key_id=virtual_key_id,
            scope=scope,
            db=db,
        )
        if virtual_key is None:
            raise WorkspaceScopeNotFoundError("not_found")
        if project_id is not None and virtual_key.project_id != project_id:
            raise WorkspaceScopeNotFoundError("virtual_key_project_mismatch")
        if project is None:
            project = await get_project_identity(
                project_id=virtual_key.project_id,
                scope=scope,
                db=db,
            )
        if project is None or (team_id is not None and project.team_id != team_id):
            raise WorkspaceScopeNotFoundError("virtual_key_team_mismatch")
    return WorkspaceFilterValidation(
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        project=project,
    )


async def expand_allowed_scope_ids(
    *,
    scope: Scope,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    db: AsyncSession,
) -> WorkspaceAllowedScopeIds | None:
    if allowed_team_ids is None and allowed_project_ids is None:
        return None
    team_ids = set(allowed_team_ids or set())
    project_ids = set(allowed_project_ids or set())
    project_ids.update(
        await projects.list_project_ids_for_team_ids(
            team_ids=team_ids,
            scope=scope,
            db=db,
        )
    )
    virtual_key_ids = await keys_runtime_facade.list_virtual_key_ids_for_project_ids(
        project_ids=project_ids,
        scope=scope,
        db=db,
    )
    return WorkspaceAllowedScopeIds(
        team_ids=team_ids,
        project_ids=project_ids,
        virtual_key_ids=virtual_key_ids,
    )


async def get_workspace_label_maps(
    *,
    scope: Scope,
    team_ids: set[UUID],
    project_ids: set[UUID],
    virtual_key_ids: set[UUID],
    db: AsyncSession,
) -> WorkspaceLabelMaps:
    return WorkspaceLabelMaps(
        teams=await teams_facade.get_team_labels(team_ids=team_ids, scope=scope, db=db),
        projects=await projects.get_project_labels(
            project_ids=project_ids,
            scope=scope,
            db=db,
        ),
        virtual_keys=await keys_runtime_facade.get_virtual_key_labels(
            virtual_key_ids=virtual_key_ids,
            scope=scope,
            db=db,
        ),
    )


async def list_workspace_projects(
    *,
    scope: Scope,
    team_ids: set[UUID] | None = None,
    project_ids: set[UUID] | None = None,
    include_all: bool = False,
    db: AsyncSession,
) -> list[WorkspaceProjectOption]:
    project_options = await projects.list_project_options(
        scope=scope,
        team_ids=None if include_all else team_ids,
        project_ids=None if include_all else project_ids,
        db=db,
    )
    return [
        WorkspaceProjectOption(id=project.id, name=project.name, team_id=project.team_id)
        for project in project_options
    ]


async def list_workspace_virtual_keys(
    *,
    scope: Scope,
    project_ids: set[UUID] | None = None,
    virtual_key_ids: set[UUID] | None = None,
    usable_only: bool = True,
    db: AsyncSession,
) -> list[WorkspaceVirtualKeyOption]:
    keys: list = []
    if project_ids is not None:
        keys.extend(
            await keys_runtime_facade.list_virtual_key_options_for_project_ids(
                project_ids=project_ids,
                usable_only=usable_only,
                scope=scope,
                db=db,
            )
        )
    if virtual_key_ids is not None:
        keys.extend(
            await keys_runtime_facade.list_virtual_key_options_by_ids(
                virtual_key_ids=virtual_key_ids,
                usable_only=usable_only,
                scope=scope,
                db=db,
            )
        )
    seen: dict[UUID, WorkspaceVirtualKeyOption] = {}
    for key in keys:
        seen[key.id] = WorkspaceVirtualKeyOption(
            id=key.id,
            name=key.name,
            project_id=key.project_id,
            project_name=key.project_name,
        )
    return sorted(seen.values(), key=lambda item: (item.project_name, item.name))


async def get_virtual_key_target(
    *, scope: Scope, virtual_key_id: UUID, db: AsyncSession
) -> WorkspaceVirtualKeyTarget | None:
    target = await keys_runtime_facade.get_usable_virtual_key_target(
        virtual_key_id=virtual_key_id,
        scope=scope,
        db=db,
    )
    if target is None:
        return None
    team = await get_team_identity(team_id=target.team_id, scope=scope, db=db)
    if team is None or not team.is_active:
        return None
    return WorkspaceVirtualKeyTarget(
        org_id=target.org_id,
        team_id=target.team_id,
        project_id=target.project_id,
        virtual_key_id=target.virtual_key_id,
        virtual_key_name=target.virtual_key_name,
    )


async def get_team_identity(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> WorkspaceTeamIdentity | None:
    team = await teams_facade.get_team_identity(team_id=team_id, scope=scope, db=db)
    if team is None:
        return None
    return WorkspaceTeamIdentity(id=team.id, org_id=team.org_id, is_active=team.is_active)


async def get_project_identity(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> WorkspaceProjectIdentity | None:
    project = await projects.get_project_identity(project_id=project_id, scope=scope, db=db)
    if project is None:
        return None
    return WorkspaceProjectIdentity(
        id=project.id,
        org_id=project.org_id,
        team_id=project.team_id,
        is_active=project.is_active,
    )


async def get_virtual_key_identity(
    *, virtual_key_id: UUID, scope: Scope, db: AsyncSession
) -> WorkspaceVirtualKeyIdentity | None:
    virtual_key = await keys_runtime_facade.get_virtual_key_identity(
        key_id=virtual_key_id,
        scope=scope,
        db=db,
    )
    if virtual_key is None:
        return None
    return WorkspaceVirtualKeyIdentity(
        id=virtual_key.id,
        org_id=virtual_key.org_id,
        project_id=virtual_key.project_id,
    )


async def has_team_membership(
    *, team_id: UUID, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    return await auth_facade.has_team_membership(
        org_id=actor.org_id,
        team_id=team_id,
        user_id=actor.id,
        db=db,
    )


async def is_team_admin(*, team_id: UUID, actor: AuthenticatedUser, db: AsyncSession) -> bool:
    return await auth_facade.has_team_admin_membership(
        org_id=actor.org_id,
        team_id=team_id,
        user_id=actor.id,
        db=db,
    )


async def has_project_membership(
    *, project_id: UUID, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    return await auth_facade.has_project_membership(
        org_id=actor.org_id,
        project_id=project_id,
        user_id=actor.id,
        db=db,
    )


async def is_project_admin(
    *, project_id: UUID, actor: AuthenticatedUser, db: AsyncSession
) -> bool:
    return await auth_facade.has_project_admin_membership(
        org_id=actor.org_id,
        project_id=project_id,
        user_id=actor.id,
        db=db,
    )


