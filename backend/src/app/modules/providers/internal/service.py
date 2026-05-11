import re
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import decrypt, encrypt
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.errors import ProviderInactiveError, ProviderNotFoundError
from app.modules.providers.internal import repository
from app.modules.providers.internal.adapters import AdapterProvider, default_adapter_registry
from app.modules.providers.internal.models import Provider
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

logger = structlog.get_logger(__name__)


async def create_provider(
    *,
    payload: CreateProviderRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResponse:
    async with transaction(db):
        provider = await repository.create_provider(
            org_id=scope.org_id,
            name=payload.name,
            slug=_slugify(payload.slug or payload.name),
            base_url=str(payload.base_url).rstrip("/"),
            api_key_encrypted=encrypt(payload.api_key),
            adapter_type=payload.adapter_type,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider.created",
                target_type="provider",
                target_id=provider.id,
                event_metadata={"name": provider.name},
            ),
            db,
        )

    logger.info("provider_created", provider_id=str(provider.id), org_id=str(scope.org_id))
    return _to_response(provider)


async def list_providers(*, scope: Scope, db: AsyncSession) -> list[ProviderResponse]:
    providers = await repository.list_providers(org_id=scope.org_id, db=db)
    return [_to_response(provider) for provider in providers]


async def get_provider(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> ProviderResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    return _to_response(provider)


async def create_provider_key(
    *,
    provider_id: UUID,
    payload: CreateProviderKeyRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderKeyResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_key = await repository.create_provider_key(
            org_id=scope.org_id,
            provider_id=provider_id,
            name=payload.name,
            key_prefix=_key_prefix(payload.api_key),
            api_key_encrypted=encrypt(payload.api_key),
            priority=payload.priority,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider_key.created",
                target_type="provider_key",
                target_id=provider_key.id,
                event_metadata={"provider_id": str(provider_id), "name": provider_key.name},
            ),
            db,
        )
    return ProviderKeyResponse.model_validate(provider_key)


async def list_provider_keys(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderKeyResponse]:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    provider_keys = await repository.list_provider_keys(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    return [ProviderKeyResponse.model_validate(provider_key) for provider_key in provider_keys]


async def get_provider_key(
    *,
    provider_key_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderKeyResponse:
    provider_key = await repository.get_provider_key(
        org_id=scope.org_id,
        provider_key_id=provider_key_id,
        db=db,
    )
    if provider_key is None:
        raise ProviderNotFoundError
    return ProviderKeyResponse.model_validate(provider_key)


async def create_provider_model(
    *,
    provider_id: UUID,
    payload: CreateProviderModelRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderModelResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_model = await repository.create_provider_model(
            org_id=scope.org_id,
            provider_id=provider_id,
            provider_model_name=payload.provider_model_name,
            alias=payload.alias,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider_model.created",
                target_type="provider_model",
                target_id=provider_model.id,
                event_metadata={
                    "provider_id": str(provider_id),
                    "provider_model_name": provider_model.provider_model_name,
                    "alias": provider_model.alias,
                },
            ),
            db,
        )
    return ProviderModelResponse.model_validate(provider_model)


async def sync_provider_models(
    *,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> list[ProviderModelResponse]:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_keys = await repository.list_provider_keys(
            org_id=scope.org_id,
            provider_id=provider_id,
            db=db,
        )
        active_key = next((key for key in provider_keys if key.is_active), None)
        if active_key is None:
            raise ProviderNotFoundError

        adapter = default_adapter_registry.get(provider.adapter_type)
        model_names = await adapter.list_models(
            provider=AdapterProvider(
                base_url=provider.base_url,
                api_key=decrypt(active_key.api_key_encrypted),
            ),
            http_client=http_client,
        )
        synced_models = []
        for model_name in sorted(set(model_names)):
            provider_model = await repository.get_provider_model_by_name(
                org_id=scope.org_id,
                provider_id=provider_id,
                provider_model_name=model_name,
                db=db,
            )
            if provider_model is None:
                provider_model = await repository.create_provider_model(
                    org_id=scope.org_id,
                    provider_id=provider_id,
                    provider_model_name=model_name,
                    alias=None,
                    db=db,
                )
            else:
                provider_model.is_active = True
                await db.flush()
            synced_models.append(provider_model)

        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider_models.synced",
                target_type="provider",
                target_id=provider.id,
                event_metadata={"model_count": len(synced_models)},
            ),
            db,
        )

    logger.info(
        "provider_models_synced",
        provider_id=str(provider_id),
        model_count=len(synced_models),
        org_id=str(scope.org_id),
    )
    return [ProviderModelResponse.model_validate(model) for model in synced_models]


async def list_provider_models(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderModelResponse]:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    provider_models = await repository.list_provider_models(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    return [
        ProviderModelResponse.model_validate(provider_model) for provider_model in provider_models
    ]


async def get_provider_model(
    *,
    provider_model_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderModelResponse:
    provider_model = await repository.get_provider_model(
        org_id=scope.org_id,
        provider_model_id=provider_model_id,
        db=db,
    )
    if provider_model is None:
        raise ProviderNotFoundError
    return ProviderModelResponse.model_validate(provider_model)


async def update_provider(
    *,
    provider_id: UUID,
    payload: UpdateProviderRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderResponse:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        credential_changed = payload.api_key is not None

        if payload.name is not None:
            provider.name = payload.name
        if payload.slug is not None:
            provider.slug = _slugify(payload.slug)
        if payload.base_url is not None:
            provider.base_url = str(payload.base_url).rstrip("/")
        if payload.adapter_type is not None:
            provider.adapter_type = payload.adapter_type
        if payload.is_active is not None:
            provider.is_active = payload.is_active
        if payload.api_key is not None:
            provider.api_key_encrypted = encrypt(payload.api_key)

        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider.updated",
                target_type="provider",
                target_id=provider.id,
            ),
            db,
        )
        if credential_changed:
            await audit_facade.record_event(
                RecordAuditEvent(
                    org_id=scope.org_id,
                    actor_user_id=actor.id,
                    event="provider.credential_changed",
                    target_type="provider",
                    target_id=provider.id,
                ),
                db,
            )

    logger.info("provider_updated", provider_id=str(provider.id), org_id=str(scope.org_id))
    return _to_response(provider)


async def deactivate_provider(
    *,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider.is_active = False
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider.deactivated",
                target_type="provider",
                target_id=provider.id,
            ),
            db,
        )

    logger.info("provider_deactivated", provider_id=str(provider_id), org_id=str(scope.org_id))


async def create_chat_completion(
    *,
    provider_id: UUID,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError

    adapter = default_adapter_registry.get(provider.adapter_type)
    return await adapter.create_chat_completion(
        provider=AdapterProvider(
            base_url=provider.base_url,
            api_key=decrypt(provider.api_key_encrypted),
        ),
        payload=payload,
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
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError

    adapter = default_adapter_registry.get(provider.adapter_type)
    return await adapter.stream_chat_completion(
        provider=AdapterProvider(
            base_url=provider.base_url,
            api_key=decrypt(provider.api_key_encrypted),
        ),
        payload=payload,
        http_client=http_client,
    )


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider


def _to_response(provider: Provider) -> ProviderResponse:
    return ProviderResponse.model_validate(provider)


def _key_prefix(api_key: str) -> str:
    return f"{api_key[:4]}..."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "provider"
