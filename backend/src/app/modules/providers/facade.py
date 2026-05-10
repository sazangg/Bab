from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.internal import service
from app.modules.providers.schemas import (
    CreateProviderKeyRequest,
    CreateProviderModelRequest,
    CreateProviderRequest,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
    ProviderKeyResponse,
    ProviderModelResponse,
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


async def create_provider_key(
    *,
    provider_id: UUID,
    payload: CreateProviderKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderKeyResponse:
    return await service.create_provider_key(
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_provider_keys(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderKeyResponse]:
    return await service.list_provider_keys(provider_id=provider_id, scope=scope, db=db)


async def create_provider_model(
    *,
    provider_id: UUID,
    payload: CreateProviderModelRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderModelResponse:
    return await service.create_provider_model(
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_provider_models(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderModelResponse]:
    return await service.list_provider_models(provider_id=provider_id, scope=scope, db=db)


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


async def create_chat_completion(
    *,
    provider_id: UUID,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionResponse:
    return await service.create_chat_completion(
        provider_id=provider_id,
        payload=payload,
        scope=scope,
        db=db,
        http_client=http_client,
    )


async def stream_chat_completion(
    *,
    provider_id: UUID,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionStream:
    return await service.stream_chat_completion(
        provider_id=provider_id,
        payload=payload,
        scope=scope,
        db=db,
        http_client=http_client,
    )
