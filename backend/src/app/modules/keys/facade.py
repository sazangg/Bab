from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.internal import access_planning, virtual_keys
from app.modules.keys.runtime_routes import ResolvedAccessPlanExplanation
from app.modules.keys.schemas import (
    AccessibleModel,
    CreatedVirtualKeyResponse,
    CreateVirtualKeyRequest,
    EffectiveAccessSummary,
    ResolveAccessPlanForSubjectRequest,
    ResolveAccessPlanForVirtualKeyRequest,
    ResolveAccessRequest,
    ResolvedAccess,
    ResolvedAccessPlan,
    ResolvedKeySubject,
    ResolveKeySubjectRequest,
    RotateVirtualKeyRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyIdentity,
    VirtualKeyInventoryPage,
    VirtualKeyOption,
    VirtualKeyResponse,
    VirtualKeyRevokeImpactResponse,
    VirtualKeyTarget,
)


async def create_virtual_key(
    *,
    project_id: UUID,
    payload: CreateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    return await virtual_keys.create_virtual_key(
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
    return await virtual_keys.list_virtual_keys(project_id=project_id, scope=scope, db=db)


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
    return await virtual_keys.list_virtual_key_inventory(
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
    return await virtual_keys.get_virtual_key(
        project_id=project_id,
        key_id=key_id,
        scope=scope,
        db=db,
    )


async def get_virtual_key_identity(
    *, key_id: UUID, scope: Scope, db: AsyncSession
) -> VirtualKeyIdentity | None:
    return await virtual_keys.get_virtual_key_identity(key_id=key_id, scope=scope, db=db)


async def get_virtual_key_labels(
    *, virtual_key_ids: set[UUID], scope: Scope, db: AsyncSession
) -> dict[UUID, str]:
    return await virtual_keys.get_virtual_key_labels(
        virtual_key_ids=virtual_key_ids,
        scope=scope,
        db=db,
    )


async def list_virtual_key_ids_for_project_ids(
    *, project_ids: set[UUID], scope: Scope, db: AsyncSession
) -> set[UUID]:
    return await virtual_keys.list_virtual_key_ids_for_project_ids(
        project_ids=project_ids,
        scope=scope,
        db=db,
    )


async def list_virtual_key_options_for_project_ids(
    *, project_ids: set[UUID], usable_only: bool, scope: Scope, db: AsyncSession
) -> list[VirtualKeyOption]:
    return await virtual_keys.list_virtual_key_options_for_project_ids(
        project_ids=project_ids,
        usable_only=usable_only,
        scope=scope,
        db=db,
    )


async def list_virtual_key_options_by_ids(
    *, virtual_key_ids: set[UUID], usable_only: bool, scope: Scope, db: AsyncSession
) -> list[VirtualKeyOption]:
    return await virtual_keys.list_virtual_key_options_by_ids(
        virtual_key_ids=virtual_key_ids,
        usable_only=usable_only,
        scope=scope,
        db=db,
    )


async def get_usable_virtual_key_target(
    *, virtual_key_id: UUID, scope: Scope, db: AsyncSession
) -> VirtualKeyTarget | None:
    return await virtual_keys.get_usable_virtual_key_target(
        virtual_key_id=virtual_key_id,
        scope=scope,
        db=db,
    )


async def rotate_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    payload: RotateVirtualKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CreatedVirtualKeyResponse:
    return await virtual_keys.rotate_virtual_key(
        project_id=project_id,
        key_id=key_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def get_virtual_key_revoke_impact(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyRevokeImpactResponse:
    return await virtual_keys.get_virtual_key_revoke_impact(
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
    return await virtual_keys.update_virtual_key(
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
    await virtual_keys.revoke_virtual_key(
        project_id=project_id,
        key_id=key_id,
        reason=reason,
        force=force,
        actor=actor,
        scope=scope,
        db=db,
    )


async def resolve_access(*, payload: ResolveAccessRequest, db: AsyncSession) -> ResolvedAccess:
    return await access_planning.resolve_access(payload=payload, db=db)


async def resolve_access_plan(
    *, payload: ResolveAccessRequest, db: AsyncSession
) -> ResolvedAccessPlan:
    return await access_planning.resolve_access_plan(payload=payload, db=db)


async def resolve_key_subject(
    *, payload: ResolveKeySubjectRequest, db: AsyncSession
) -> ResolvedKeySubject:
    return await access_planning.resolve_key_subject(payload=payload, db=db)


async def resolve_access_plan_for_subject(
    *, payload: ResolveAccessPlanForSubjectRequest, db: AsyncSession
) -> ResolvedAccessPlan:
    return await access_planning.resolve_access_plan_for_subject(payload=payload, db=db)


async def resolve_access_plan_for_virtual_key(
    *,
    org_id: UUID,
    payload: ResolveAccessPlanForVirtualKeyRequest,
    db: AsyncSession,
) -> ResolvedAccessPlan:
    return await access_planning.resolve_access_plan_for_virtual_key(
        org_id=org_id, payload=payload, db=db
    )


async def explain_access_plan_for_virtual_key(
    *,
    org_id: UUID,
    payload: ResolveAccessPlanForVirtualKeyRequest,
    db: AsyncSession,
) -> ResolvedAccessPlanExplanation:
    return await access_planning.explain_access_plan_for_virtual_key(
        org_id=org_id, payload=payload, db=db
    )


async def list_accessible_models(*, raw_key: str, db: AsyncSession) -> list[AccessibleModel]:
    return await access_planning.list_accessible_models(raw_key=raw_key, db=db)


async def list_project_accessible_models(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> list[AccessibleModel]:
    return await access_planning.list_project_accessible_models(
        project_id=project_id, scope=scope, db=db
    )


async def get_project_effective_access(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    return await access_planning.get_project_effective_access(
        project_id=project_id, scope=scope, db=db
    )


async def get_virtual_key_effective_access(
    *, project_id: UUID, key_id: UUID, scope: Scope, db: AsyncSession
) -> EffectiveAccessSummary:
    return await access_planning.get_virtual_key_effective_access(
        project_id=project_id, key_id=key_id, scope=scope, db=db
    )
