from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.internal import service
from app.modules.keys.schemas import (
    AccessibleModel,
    CreatedVirtualKeyResponse,
    CreateProjectRequest,
    CreateVirtualKeyRequest,
    EffectiveAccessSummary,
    ProjectArchiveImpactResponse,
    ProjectResponse,
    ResolveAccessRequest,
    RotateVirtualKeyRequest,
    ResolvedAccess,
    TeamArchiveImpactResponse,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyInventoryPage,
    VirtualKeyResponse,
    VirtualKeyRevokeImpactResponse,
)


async def create_project(
    *,
    team_id: UUID,
    payload: CreateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    return await service.create_project(
        team_id=team_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    return await service.list_projects(scope=scope, db=db)


async def get_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> ProjectResponse:
    return await service.get_project(project_id=project_id, scope=scope, db=db)


async def list_team_projects(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectResponse]:
    return await service.list_team_projects(team_id=team_id, scope=scope, db=db)


async def get_team_archive_impact(
    *,
    team_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> TeamArchiveImpactResponse:
    return await service.get_team_archive_impact(team_id=team_id, scope=scope, db=db)


async def update_project(
    *,
    project_id: UUID,
    payload: UpdateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    return await service.update_project(
        project_id=project_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_project(
    *,
    project_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_project(project_id=project_id, actor=actor, scope=scope, db=db)


async def create_virtual_key(
    *,
    project_id: UUID,
    payload: CreateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    return await service.create_virtual_key(
        project_id=project_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_virtual_keys(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[VirtualKeyResponse]:
    return await service.list_virtual_keys(project_id=project_id, scope=scope, db=db)


async def list_virtual_key_inventory(
    *,
    scope: Scope,
    visible_team_ids: set[UUID] | None,
    visible_project_ids: set[UUID] | None,
    manageable_team_ids: set[UUID],
    manageable_project_ids: set[UUID],
    can_manage_all: bool,
    team_id: UUID | None,
    project_id: UUID | None,
    status: str | None,
    search: str | None,
    usage: str | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> VirtualKeyInventoryPage:
    return await service.list_virtual_key_inventory(
        scope=scope,
        visible_team_ids=visible_team_ids,
        visible_project_ids=visible_project_ids,
        manageable_team_ids=manageable_team_ids,
        manageable_project_ids=manageable_project_ids,
        can_manage_all=can_manage_all,
        team_id=team_id,
        project_id=project_id,
        status=status,
        search=search,
        usage=usage,
        limit=limit,
        offset=offset,
        db=db,
    )


async def get_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    return await service.get_virtual_key(project_id=project_id, key_id=key_id, scope=scope, db=db)


async def rotate_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    payload: RotateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    return await service.rotate_virtual_key(
        project_id=project_id,
        key_id=key_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def get_project_archive_impact(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProjectArchiveImpactResponse:
    return await service.get_project_archive_impact(project_id=project_id, scope=scope, db=db)


async def get_virtual_key_revoke_impact(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyRevokeImpactResponse:
    return await service.get_virtual_key_revoke_impact(
        project_id=project_id,
        key_id=key_id,
        scope=scope,
        db=db,
    )


async def update_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    payload: UpdateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    return await service.update_virtual_key(
        project_id=project_id,
        key_id=key_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def revoke_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    reason: str,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    force: bool = False,
) -> None:
    await service.revoke_virtual_key(
        project_id=project_id,
        key_id=key_id,
        reason=reason,
        force=force,
        actor=actor,
        scope=scope,
        db=db,
    )


async def resolve_access(*, payload: ResolveAccessRequest, db: AsyncSession) -> ResolvedAccess:
    return await service.resolve_access(payload=payload, db=db)


async def list_accessible_models(*, raw_key: str, db: AsyncSession) -> list[AccessibleModel]:
    return await service.list_accessible_models(raw_key=raw_key, db=db)


async def list_project_accessible_models(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> list[AccessibleModel]:
    return await service.list_project_accessible_models(project_id=project_id, scope=scope, db=db)


async def get_project_effective_access(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    return await service.get_project_effective_access(project_id=project_id, scope=scope, db=db)


async def get_virtual_key_effective_access(
    *, project_id: UUID, key_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    return await service.get_virtual_key_effective_access(
        project_id=project_id, key_id=key_id, scope=scope, db=db
    )
