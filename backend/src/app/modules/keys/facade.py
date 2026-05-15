from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys.internal import service
from app.modules.keys.schemas import (
    AttachSubscriptionProviderKeyRequest,
    CreatedVirtualKeyResponse,
    CreateModelAliasRequest,
    CreateProjectAllocationRequest,
    CreateProjectRequest,
    CreateSubscriptionRequest,
    CreateVirtualKeyRequest,
    GrantProjectProviderAccessRequest,
    GrantProjectSubscriptionAccessRequest,
    ModelAliasResponse,
    ProjectAllocationResponse,
    ProjectProviderAccessResponse,
    ProjectResponse,
    ProjectSubscriptionAccessResponse,
    ResolveAccessRequest,
    ResolvedAccess,
    SetSubscriptionModelAccessRequest,
    SubscriptionModelAccessResponse,
    SubscriptionProviderKeyResponse,
    SubscriptionResponse,
    UpdateModelAliasRequest,
    UpdateProjectAllocationRequest,
    UpdateProjectProviderAccessRequest,
    UpdateProjectRequest,
    UpdateVirtualKeyRequest,
    VirtualKeyResponse,
)


async def create_project(
    *,
    payload: CreateProjectRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectResponse:
    return await service.create_project(payload=payload, actor=actor, scope=scope, db=db)


async def list_projects(*, scope: Scope, db: AsyncSession) -> list[ProjectResponse]:
    return await service.list_projects(scope=scope, db=db)


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


async def grant_project_provider_access(
    *,
    project_id: UUID,
    payload: GrantProjectProviderAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectProviderAccessResponse:
    return await service.grant_project_provider_access(
        project_id=project_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_project_provider_access(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectProviderAccessResponse]:
    return await service.list_project_provider_access(project_id=project_id, scope=scope, db=db)


async def update_project_provider_access(
    *,
    project_id: UUID,
    provider_id: UUID,
    payload: UpdateProjectProviderAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectProviderAccessResponse:
    return await service.update_project_provider_access(
        project_id=project_id,
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def revoke_project_provider_access(
    *,
    project_id: UUID,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.revoke_project_provider_access(
        project_id=project_id,
        provider_id=provider_id,
        actor=actor,
        scope=scope,
        db=db,
    )


async def create_project_allocation(
    *,
    project_id: UUID,
    payload: CreateProjectAllocationRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectAllocationResponse:
    return await service.create_project_allocation(
        project_id=project_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_project_allocations(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectAllocationResponse]:
    return await service.list_project_allocations(project_id=project_id, scope=scope, db=db)


async def update_project_allocation(
    *,
    project_id: UUID,
    provider_id: UUID,
    payload: UpdateProjectAllocationRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectAllocationResponse:
    return await service.update_project_allocation(
        project_id=project_id,
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def revoke_project_allocation(
    *,
    project_id: UUID,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.revoke_project_allocation(
        project_id=project_id,
        provider_id=provider_id,
        actor=actor,
        scope=scope,
        db=db,
    )


async def create_subscription(
    *,
    payload: CreateSubscriptionRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> SubscriptionResponse:
    return await service.create_subscription(payload=payload, actor=actor, scope=scope, db=db)


async def list_subscriptions(*, scope: Scope, db: AsyncSession) -> list[SubscriptionResponse]:
    return await service.list_subscriptions(scope=scope, db=db)


async def attach_provider_key_to_subscription(
    *,
    subscription_id: UUID,
    payload: AttachSubscriptionProviderKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> SubscriptionProviderKeyResponse:
    return await service.attach_provider_key_to_subscription(
        subscription_id=subscription_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_subscription_provider_keys(
    *,
    subscription_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[SubscriptionProviderKeyResponse]:
    return await service.list_subscription_provider_keys(
        subscription_id=subscription_id,
        scope=scope,
        db=db,
    )


async def set_subscription_model_access(
    *,
    subscription_id: UUID,
    payload: SetSubscriptionModelAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> list[SubscriptionModelAccessResponse]:
    return await service.set_subscription_model_access(
        subscription_id=subscription_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_subscription_model_access(
    *,
    subscription_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[SubscriptionModelAccessResponse]:
    return await service.list_subscription_model_access(
        subscription_id=subscription_id,
        scope=scope,
        db=db,
    )


async def grant_project_subscription_access(
    *,
    project_id: UUID,
    payload: GrantProjectSubscriptionAccessRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectSubscriptionAccessResponse:
    return await service.grant_project_subscription_access(
        project_id=project_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_project_subscription_access(
    *,
    project_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProjectSubscriptionAccessResponse]:
    return await service.list_project_subscription_access(
        project_id=project_id,
        scope=scope,
        db=db,
    )


async def create_model_alias(
    *,
    payload: CreateModelAliasRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelAliasResponse:
    return await service.create_model_alias(payload=payload, actor=actor, scope=scope, db=db)


async def list_model_aliases(*, scope: Scope, db: AsyncSession) -> list[ModelAliasResponse]:
    return await service.list_model_aliases(scope=scope, db=db)


async def update_model_alias(
    *,
    alias_id: UUID,
    payload: UpdateModelAliasRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelAliasResponse:
    return await service.update_model_alias(
        alias_id=alias_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_model_alias(
    *,
    alias_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_model_alias(alias_id=alias_id, actor=actor, scope=scope, db=db)


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


async def get_virtual_key(
    *,
    project_id: UUID,
    key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> VirtualKeyResponse:
    return await service.get_virtual_key(project_id=project_id, key_id=key_id, scope=scope, db=db)


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
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.revoke_virtual_key(
        project_id=project_id,
        key_id=key_id,
        actor=actor,
        scope=scope,
        db=db,
    )


async def resolve_access(*, payload: ResolveAccessRequest, db: AsyncSession) -> ResolvedAccess:
    return await service.resolve_access(payload=payload, db=db)
