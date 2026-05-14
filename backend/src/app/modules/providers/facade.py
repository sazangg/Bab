from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.internal import service
from app.modules.providers.schemas import (
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    ModelMetadataSyncMode,
    ModelOfferingPageResponse,
    ModelOfferingResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
    ProviderCredentialResponse,
    ProviderResponse,
    TestProviderCredentialResponse,
    UpdateModelOfferingRequest,
    UpdateProviderCredentialRequest,
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


async def create_provider_credential(
    *,
    provider_id: UUID,
    payload: CreateProviderCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    return await service.create_provider_credential(
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_provider_credentials(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderCredentialResponse]:
    return await service.list_provider_credentials(provider_id=provider_id, scope=scope, db=db)


async def get_provider_credential(
    *,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    return await service.get_provider_credential(
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )


async def update_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    payload: UpdateProviderCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    return await service.update_provider_credential(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def test_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> TestProviderCredentialResponse:
    return await service.test_provider_credential(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        actor=actor,
        scope=scope,
        db=db,
        http_client=http_client,
    )


async def deactivate_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_provider_credential(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        actor=actor,
        scope=scope,
        db=db,
    )


async def create_model_offering(
    *,
    provider_id: UUID,
    payload: CreateModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelOfferingResponse:
    return await service.create_model_offering(
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def sync_model_offerings(
    *,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    metadata_mode: ModelMetadataSyncMode,
) -> list[ModelOfferingResponse]:
    return await service.sync_model_offerings(
        provider_id=provider_id,
        actor=actor,
        scope=scope,
        db=db,
        http_client=http_client,
        metadata_mode=metadata_mode,
    )


async def list_model_offerings(
    *,
    provider_id: UUID,
    search: str | None,
    modalities: list[str] | None,
    is_active: bool | None,
    limit: int,
    offset: int,
    scope: Scope,
    db: AsyncSession,
) -> ModelOfferingPageResponse:
    return await service.list_model_offerings(
        provider_id=provider_id,
        search=search,
        modalities=modalities,
        is_active=is_active,
        limit=limit,
        offset=offset,
        scope=scope,
        db=db,
    )


async def get_model_offering(
    *,
    model_offering_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ModelOfferingResponse:
    return await service.get_model_offering(
        model_offering_id=model_offering_id,
        scope=scope,
        db=db,
    )


async def update_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    payload: UpdateModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelOfferingResponse:
    return await service.update_model_offering(
        provider_id=provider_id,
        model_offering_id=model_offering_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def deactivate_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.deactivate_model_offering(
        provider_id=provider_id,
        model_offering_id=model_offering_id,
        actor=actor,
        scope=scope,
        db=db,
    )


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
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionResponse:
    return await service.create_chat_completion(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        scope=scope,
        db=db,
        http_client=http_client,
    )


async def stream_chat_completion(
    *,
    provider_id: UUID,
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionStream:
    return await service.stream_chat_completion(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        scope=scope,
        db=db,
        http_client=http_client,
    )

