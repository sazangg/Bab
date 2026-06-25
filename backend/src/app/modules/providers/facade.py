from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.internal import credentials, execution, impact, model_offerings, service
from app.modules.providers.internal.secret_backends import ProviderSecretBackendRegistry
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateProviderCredentialRequest,
    CreateProviderModelOfferingRequest,
    CreateProviderRequest,
    CredentialPoolCredentialResponse,
    CredentialPoolResponse,
    ModelMetadataSyncMode,
    ProviderAnthropicMessagesRequest,
    ProviderAnthropicMessagesResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
    ProviderCredentialResponse,
    ProviderImpactResponse,
    ProviderModelOfferingPageResponse,
    ProviderModelOfferingResponse,
    ProviderResourceImpactResponse,
    ProviderResponse,
    SyncProviderModelOfferingsResponse,
    TestProviderCredentialResponse,
    TestProviderModelOfferingRequest,
    TestProviderModelOfferingResponse,
    UpdateCredentialPoolCredentialRequest,
    UpdateCredentialPoolRequest,
    UpdateProviderCredentialRequest,
    UpdateProviderModelOfferingRequest,
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


async def get_provider_impact(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderImpactResponse:
    return await impact.get_provider_impact(provider_id=provider_id, scope=scope, db=db)


async def get_provider_credential_impact(
    *, provider_id: UUID, provider_credential_id: UUID, scope: Scope, db: AsyncSession
) -> ProviderResourceImpactResponse:
    return await impact.get_provider_credential_impact(
        provider_id=provider_id, provider_credential_id=provider_credential_id, scope=scope, db=db
    )


async def get_credential_pool_impact(
    *, provider_id: UUID, pool_id: UUID, scope: Scope, db: AsyncSession
) -> ProviderResourceImpactResponse:
    return await impact.get_credential_pool_impact(
        provider_id=provider_id, pool_id=pool_id, scope=scope, db=db
    )


async def get_model_offering_impact(
    *, provider_id: UUID, model_offering_id: UUID, scope: Scope, db: AsyncSession
) -> ProviderResourceImpactResponse:
    return await impact.get_model_offering_impact(
        provider_id=provider_id, model_offering_id=model_offering_id, scope=scope, db=db
    )


async def create_credential_pool(
    *,
    provider_id: UUID,
    payload: CreateCredentialPoolRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    return await credentials.create_credential_pool(
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_credential_pools(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[CredentialPoolResponse]:
    return await credentials.list_credential_pools(provider_id=provider_id, scope=scope, db=db)


async def get_credential_pool(
    *,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    return await credentials.get_credential_pool(pool_id=pool_id, scope=scope, db=db)


async def update_credential_pool(
    *,
    provider_id: UUID,
    pool_id: UUID,
    payload: UpdateCredentialPoolRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    return await credentials.update_credential_pool(
        provider_id=provider_id,
        pool_id=pool_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_credential_pool_credentials(
    *,
    provider_id: UUID,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[CredentialPoolCredentialResponse]:
    return await credentials.list_credential_pool_credentials(
        provider_id=provider_id,
        pool_id=pool_id,
        scope=scope,
        db=db,
    )


async def add_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    payload: AddCredentialPoolCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolCredentialResponse:
    return await credentials.add_credential_pool_credential(
        provider_id=provider_id,
        pool_id=pool_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def update_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    pool_credential_id: UUID,
    payload: UpdateCredentialPoolCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolCredentialResponse:
    return await credentials.update_credential_pool_credential(
        provider_id=provider_id,
        pool_id=pool_id,
        pool_credential_id=pool_credential_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def delete_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    pool_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await credentials.delete_credential_pool_credential(
        provider_id=provider_id,
        pool_id=pool_id,
        pool_credential_id=pool_credential_id,
        actor=actor,
        scope=scope,
        db=db,
    )


async def create_provider_credential(
    *,
    provider_id: UUID,
    payload: CreateProviderCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderCredentialResponse:
    return await credentials.create_provider_credential(
        provider_id=provider_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
        secret_registry=secret_registry,
    )


async def list_provider_credentials(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderCredentialResponse]:
    return await credentials.list_provider_credentials(provider_id=provider_id, scope=scope, db=db)


async def get_provider_credential(
    *,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    return await credentials.get_provider_credential(
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
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderCredentialResponse:
    return await credentials.update_provider_credential(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
        secret_registry=secret_registry,
    )


async def test_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> TestProviderCredentialResponse:
    return await credentials.test_provider_credential(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        actor=actor,
        scope=scope,
        db=db,
        http_client=http_client,
        secret_registry=secret_registry,
    )


async def deactivate_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await credentials.deactivate_provider_credential(
        provider_id=provider_id,
        provider_credential_id=provider_credential_id,
        actor=actor,
        scope=scope,
        db=db,
    )


async def create_model_offering(
    *,
    provider_id: UUID,
    payload: CreateProviderModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderModelOfferingResponse:
    return await model_offerings.create_model_offering(
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
    sync_mode: str = "merge",
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> SyncProviderModelOfferingsResponse:
    return await model_offerings.sync_model_offerings(
        provider_id=provider_id,
        actor=actor,
        scope=scope,
        db=db,
        http_client=http_client,
        metadata_mode=metadata_mode,
        sync_mode=sync_mode,
        secret_registry=secret_registry,
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
) -> ProviderModelOfferingPageResponse:
    return await model_offerings.list_model_offerings(
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
) -> ProviderModelOfferingResponse:
    return await model_offerings.get_model_offering(
        model_offering_id=model_offering_id,
        scope=scope,
        db=db,
    )


async def test_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    payload: TestProviderModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> TestProviderModelOfferingResponse:
    return await model_offerings.test_model_offering(
        provider_id=provider_id,
        model_offering_id=model_offering_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
        http_client=http_client,
        secret_registry=secret_registry,
    )


async def update_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    payload: UpdateProviderModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderModelOfferingResponse:
    return await model_offerings.update_model_offering(
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
    await model_offerings.deactivate_model_offering(
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
    pool_id: UUID | None = None,
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderChatCompletionResponse:
    return await execution.create_chat_completion(
        provider_id=provider_id,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        scope=scope,
        db=db,
        http_client=http_client,
        secret_registry=secret_registry,
    )


async def create_anthropic_message(
    *,
    provider_id: UUID,
    pool_id: UUID | None,
    provider_credential_id: UUID | None,
    payload: ProviderAnthropicMessagesRequest,
    anthropic_version: str,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderAnthropicMessagesResponse:
    return await execution.create_anthropic_message(
        provider_id=provider_id,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        anthropic_version=anthropic_version,
        scope=scope,
        db=db,
        http_client=http_client,
        secret_registry=secret_registry,
    )


async def stream_chat_completion(
    *,
    provider_id: UUID,
    pool_id: UUID | None = None,
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderChatCompletionStream:
    return await execution.stream_chat_completion(
        provider_id=provider_id,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        scope=scope,
        db=db,
        http_client=http_client,
        secret_registry=secret_registry,
    )
