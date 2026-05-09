from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.internal import service
from app.modules.providers.schemas import (
    CreateProviderRequest,
    ProviderResponse,
    UpdateProviderRequest,
)


async def create_provider(
    *,
    payload: CreateProviderRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResponse:
    return await service.create_provider(payload=payload, actor=actor, scope=scope, db=db)


async def list_providers(*, scope: Scope, db: AsyncSession) -> list[ProviderResponse]:
    return await service.list_providers(scope=scope, db=db)


async def get_provider(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> ProviderResponse:
    return await service.get_provider(provider_id=provider_id, scope=scope, db=db)


async def update_provider(
    *,
    provider_id: UUID,
    payload: UpdateProviderRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResponse:
    return await service.update_provider(
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_provider(
    *,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_provider(provider_id=provider_id, actor=actor, scope=scope, db=db)
