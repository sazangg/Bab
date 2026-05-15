import re
import secrets
from datetime import UTC, datetime
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import decrypt, encrypt
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.errors import (
    ProviderCredentialRequiredError,
    ProviderInactiveError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.internal import repository
from app.modules.providers.internal.adapters import (
    OPENAI_COMPAT_ADAPTER,
    AdapterProvider,
    default_adapter_registry,
)
from app.modules.providers.internal.model_metadata import (
    ModelMetadata,
    default_model_metadata_registry,
)
from app.modules.providers.internal.models import ModelOffering, Provider, ProviderCredential
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
    ProviderCredentialRoutingPolicy,
    ProviderResponse,
    TestProviderCredentialResponse,
    UpdateModelOfferingRequest,
    UpdateProviderCredentialRequest,
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
            api_key_encrypted=encrypt(payload.api_key) if payload.api_key is not None else None,
            adapter_type=OPENAI_COMPAT_ADAPTER,
            description=payload.description,
            capabilities=payload.capabilities or _default_capabilities(),
            request_timeout_seconds=payload.request_timeout_seconds,
            max_body_bytes=payload.max_body_bytes,
            retry_policy=payload.retry_policy,
            fallback_policy=payload.fallback_policy,
            circuit_breaker_policy=payload.circuit_breaker_policy,
            max_concurrent_requests=payload.max_concurrent_requests,
            credential_routing_policy=payload.credential_routing_policy,
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


async def create_provider_credential(
    *,
    provider_id: UUID,
    payload: CreateProviderCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        api_key = _normalize_api_key(payload.api_key)
        provider_credential = await repository.create_provider_credential(
            org_id=scope.org_id,
            provider_id=provider_id,
            created_by=actor.id,
            name=payload.name,
            key_prefix=_key_prefix(api_key),
            api_key_encrypted=encrypt(api_key),
            priority=payload.priority,
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider_credential.created",
                target_type="provider_credential",
                target_id=provider_credential.id,
                event_metadata={"provider_id": str(provider_id), "name": provider_credential.name},
            ),
            db,
        )
    return ProviderCredentialResponse.model_validate(provider_credential)


async def list_provider_credentials(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderCredentialResponse]:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    provider_credentials = await repository.list_provider_credentials(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    return [
        ProviderCredentialResponse.model_validate(provider_credential)
        for provider_credential in provider_credentials
    ]


async def get_provider_credential(
    *,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    provider_credential = await repository.get_provider_credential(
        org_id=scope.org_id,
        provider_credential_id=provider_credential_id,
        db=db,
    )
    if provider_credential is None:
        raise ProviderNotFoundError
    return ProviderCredentialResponse.model_validate(provider_credential)


async def update_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    payload: UpdateProviderCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderCredentialResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            scope=scope,
            db=db,
        )
        credential_changed = payload.api_key is not None
        if payload.name is not None:
            provider_credential.name = payload.name
        if payload.api_key is not None:
            api_key = _normalize_api_key(payload.api_key)
            provider_credential.key_prefix = _key_prefix(api_key)
            provider_credential.api_key_encrypted = encrypt(api_key)
            provider_credential.health_status = "unchecked"
            provider_credential.last_validation_error = None
        if payload.priority is not None:
            provider_credential.priority = payload.priority
        if payload.is_active is not None:
            provider_credential.is_active = payload.is_active

        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider_credential.updated",
                target_type="provider_credential",
                target_id=provider_credential.id,
                event_metadata={"provider_id": str(provider_id)},
            ),
            db,
        )
        if credential_changed:
            await audit_facade.record_event(
                RecordAuditEvent(
                    org_id=scope.org_id,
                    actor_user_id=actor.id,
                    event="provider_credential.secret_changed",
                    target_type="provider_credential",
                    target_id=provider_credential.id,
                    event_metadata={"provider_id": str(provider_id)},
                ),
                db,
            )

    return ProviderCredentialResponse.model_validate(provider_credential)


async def test_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> TestProviderCredentialResponse:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            scope=scope,
            db=db,
        )
        try:
            adapter = default_adapter_registry.get(provider.adapter_type)
            await adapter.list_models(
                provider=AdapterProvider(
                    base_url=provider.base_url,
                    api_key=decrypt(provider_credential.api_key_encrypted),
                ),
                http_client=http_client,
            )
            provider_credential.health_status = "valid"
            provider_credential.last_validation_error = None
            provider_credential.last_successful_request_at = repository.datetime_now()
            health_status = "valid"
            error = None
            last_successful_request_at = provider_credential.last_successful_request_at
        except Exception as exc:  # noqa: BLE001 - persisted as upstream credential health.
            provider_credential.health_status = "invalid"
            provider_credential.last_validation_error = str(exc)
            health_status = "invalid"
            error = str(exc)
            last_successful_request_at = provider_credential.last_successful_request_at
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider_credential.tested",
                target_type="provider_credential",
                target_id=provider_credential.id,
                event_metadata={"provider_id": str(provider_id), "health_status": health_status},
            ),
            db,
        )

    return TestProviderCredentialResponse(
        id=provider_credential.id,
        health_status=health_status,
        last_validation_error=error,
        last_successful_request_at=last_successful_request_at,
    )


async def deactivate_provider_credential(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=provider_credential_id,
            scope=scope,
            db=db,
        )
        provider_credential.is_active = False
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="provider_credential.deactivated",
                target_type="provider_credential",
                target_id=provider_credential.id,
                event_metadata={"provider_id": str(provider_id)},
            ),
            db,
        )


async def create_model_offering(
    *,
    provider_id: UUID,
    payload: CreateModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelOfferingResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        model_offering = await repository.create_model_offering(
            org_id=scope.org_id,
            provider_id=provider_id,
            provider_model_name=payload.provider_model_name,
            alias=payload.alias,
            version=payload.version,
            modality=payload.modality,
            input_modalities=payload.input_modalities,
            output_modalities=payload.output_modalities,
            capabilities=payload.capabilities,
            context_window=payload.context_window,
            input_price_per_million_tokens=payload.input_price_per_million_tokens,
            output_price_per_million_tokens=payload.output_price_per_million_tokens,
            cached_input_price_per_million_tokens=payload.cached_input_price_per_million_tokens,
            rate_limit_hints=payload.rate_limit_hints,
            metadata_source="manual",
            db=db,
        )
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="model_offering.created",
                target_type="model_offering",
                target_id=model_offering.id,
                event_metadata={
                    "provider_id": str(provider_id),
                    "provider_model_name": model_offering.provider_model_name,
                    "alias": model_offering.alias,
                },
            ),
            db,
        )
    return ModelOfferingResponse.model_validate(model_offering)


async def sync_model_offerings(
    *,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    metadata_mode: ModelMetadataSyncMode,
) -> list[ModelOfferingResponse]:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        provider_credentials = await repository.list_provider_credentials(
            org_id=scope.org_id,
            provider_id=provider_id,
            db=db,
        )
        active_credential = next(
            (credential for credential in provider_credentials if credential.is_active),
            None,
        )
        if active_credential is None:
            raise ProviderCredentialRequiredError
        await repository.mark_provider_credential_used(
            provider_credential=active_credential,
            db=db,
        )

        adapter = default_adapter_registry.get(provider.adapter_type)
        model_names = await adapter.list_models(
            provider=AdapterProvider(
                base_url=provider.base_url,
                api_key=decrypt(active_credential.api_key_encrypted),
            ),
            http_client=http_client,
        )
        synced_models = []
        synced_at = datetime.now(UTC)
        for model_name in sorted(set(model_names)):
            metadata = default_model_metadata_registry.get(
                provider=provider,
                provider_model_name=model_name,
            )
            model_offering = await repository.get_model_offering_by_name(
                org_id=scope.org_id,
                provider_id=provider_id,
                provider_model_name=model_name,
                db=db,
            )
            if model_offering is None:
                model_offering = await repository.create_model_offering(
                    org_id=scope.org_id,
                    provider_id=provider_id,
                    provider_model_name=model_name,
                    alias=None,
                    version=metadata.version if metadata else None,
                    modality=(
                        _combined_modality(metadata.input_modalities, metadata.output_modalities)
                        if metadata
                        else "text"
                    ),
                    input_modalities=metadata.input_modalities if metadata else ["text"],
                    output_modalities=metadata.output_modalities if metadata else ["text"],
                    capabilities=(
                        metadata.capabilities if metadata else _default_model_capabilities()
                    ),
                    context_window=metadata.context_window if metadata else None,
                    input_price_per_million_tokens=(
                        metadata.pricing.input_price_per_million_tokens if metadata else None
                    ),
                    output_price_per_million_tokens=(
                        metadata.pricing.output_price_per_million_tokens if metadata else None
                    ),
                    cached_input_price_per_million_tokens=(
                        metadata.pricing.cached_input_price_per_million_tokens if metadata else None
                    ),
                    rate_limit_hints=metadata.rate_limit_hints if metadata else {},
                    metadata_source="catalog" if metadata else "provider",
                    db=db,
                )
                model_offering.metadata_last_synced_at = synced_at
            else:
                model_offering.is_active = True
                model_offering.metadata_last_synced_at = synced_at
                if metadata is not None:
                    if metadata_mode == ModelMetadataSyncMode.overwrite_catalog:
                        _overwrite_model_offering_from_metadata(
                            model_offering=model_offering,
                            metadata=metadata,
                        )
                    else:
                        _enrich_model_offering_from_metadata(
                            model_offering=model_offering,
                            metadata=metadata,
                        )
                await db.flush()
            synced_models.append(model_offering)

        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="model_offerings.synced",
                target_type="provider",
                target_id=provider.id,
                event_metadata={"model_count": len(synced_models)},
            ),
            db,
        )

    logger.info(
        "model_offerings_synced",
        provider_id=str(provider_id),
        model_count=len(synced_models),
        org_id=str(scope.org_id),
    )
    return [
        ModelOfferingResponse.model_validate(model_offering)
        for model_offering in synced_models
    ]


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
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    model_offerings, total = await repository.list_model_offerings(
        org_id=scope.org_id,
        provider_id=provider_id,
        search=search,
        modalities=modalities,
        is_active=is_active,
        limit=limit,
        offset=offset,
        db=db,
    )
    return ModelOfferingPageResponse(
        items=[
            ModelOfferingResponse.model_validate(model_offering)
            for model_offering in model_offerings
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_model_offering(
    *,
    model_offering_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ModelOfferingResponse:
    model_offering = await repository.get_model_offering(
        org_id=scope.org_id,
        model_offering_id=model_offering_id,
        db=db,
    )
    if model_offering is None:
        raise ProviderNotFoundError
    return ModelOfferingResponse.model_validate(model_offering)


async def update_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    payload: UpdateModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ModelOfferingResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        model_offering = await _get_model_offering_or_raise(
            provider_id=provider_id,
            model_offering_id=model_offering_id,
            scope=scope,
            db=db,
        )
        if payload.provider_model_name is not None:
            model_offering.provider_model_name = payload.provider_model_name
        if "alias" in payload.model_fields_set:
            model_offering.alias = payload.alias
        if "version" in payload.model_fields_set:
            model_offering.version = payload.version
        if payload.modality is not None:
            model_offering.modality = payload.modality
        if payload.input_modalities is not None:
            model_offering.input_modalities = payload.input_modalities
        if payload.output_modalities is not None:
            model_offering.output_modalities = payload.output_modalities
        if payload.input_modalities is not None or payload.output_modalities is not None:
            model_offering.modality = _combined_modality(
                model_offering.input_modalities,
                model_offering.output_modalities,
            )
        if payload.capabilities is not None:
            model_offering.capabilities = payload.capabilities
        if "context_window" in payload.model_fields_set:
            model_offering.context_window = payload.context_window
        if "input_price_per_million_tokens" in payload.model_fields_set:
            model_offering.input_price_per_million_tokens = payload.input_price_per_million_tokens
        if "output_price_per_million_tokens" in payload.model_fields_set:
            model_offering.output_price_per_million_tokens = payload.output_price_per_million_tokens
        if "cached_input_price_per_million_tokens" in payload.model_fields_set:
            model_offering.cached_input_price_per_million_tokens = (
                payload.cached_input_price_per_million_tokens
            )
        if payload.rate_limit_hints is not None:
            model_offering.rate_limit_hints = payload.rate_limit_hints
        if payload.is_active is not None:
            model_offering.is_active = payload.is_active
        model_offering.metadata_source = "manual"

        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="model_offering.updated",
                target_type="model_offering",
                target_id=model_offering.id,
                event_metadata={"provider_id": str(provider_id)},
            ),
            db,
        )

    return ModelOfferingResponse.model_validate(model_offering)


async def deactivate_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        model_offering = await _get_model_offering_or_raise(
            provider_id=provider_id,
            model_offering_id=model_offering_id,
            scope=scope,
            db=db,
        )
        model_offering.is_active = False
        await db.flush()
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=scope.org_id,
                actor_user_id=actor.id,
                event="model_offering.deactivated",
                target_type="model_offering",
                target_id=model_offering.id,
                event_metadata={"provider_id": str(provider_id)},
            ),
            db,
        )


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
        if "description" in payload.model_fields_set:
            provider.description = payload.description
        if payload.capabilities is not None:
            provider.capabilities = payload.capabilities
        if payload.request_timeout_seconds is not None:
            provider.request_timeout_seconds = payload.request_timeout_seconds
        if "max_body_bytes" in payload.model_fields_set:
            provider.max_body_bytes = payload.max_body_bytes
        if payload.retry_policy is not None:
            provider.retry_policy = payload.retry_policy
        if payload.fallback_policy is not None:
            provider.fallback_policy = payload.fallback_policy
        if payload.circuit_breaker_policy is not None:
            provider.circuit_breaker_policy = payload.circuit_breaker_policy
        if "max_concurrent_requests" in payload.model_fields_set:
            provider.max_concurrent_requests = payload.max_concurrent_requests
        if payload.credential_routing_policy is not None:
            provider.credential_routing_policy = payload.credential_routing_policy
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
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError

    adapter = default_adapter_registry.get(provider.adapter_type)
    routed_credentials = await _resolve_provider_credential_route(
        provider=provider,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    last_error: ProviderUpstreamError | None = None
    for credential in routed_credentials:
        try:
            response = await adapter.create_chat_completion(
                provider=AdapterProvider(
                    base_url=provider.base_url,
                    api_key=_api_key_for_routed_credential(
                        provider=provider,
                        credential=credential,
                    ),
                ),
                payload=payload,
                http_client=http_client,
            )
            if credential is not None:
                await repository.mark_provider_credential_used(
                    provider_credential=credential,
                    db=db,
                )
            return response
        except ProviderUpstreamError as exc:
            last_error = exc
            if credential is not None:
                await _mark_provider_credential_failed(
                    provider_credential=credential,
                    error=exc,
                    db=db,
                )
            if provider_credential_id is not None or not _should_try_next_credential(exc):
                raise
    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


async def stream_chat_completion(
    *,
    provider_id: UUID,
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionStream:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError

    adapter = default_adapter_registry.get(provider.adapter_type)
    routed_credentials = await _resolve_provider_credential_route(
        provider=provider,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    last_error: ProviderUpstreamError | None = None
    for credential in routed_credentials:
        try:
            stream = await adapter.stream_chat_completion(
                provider=AdapterProvider(
                    base_url=provider.base_url,
                    api_key=_api_key_for_routed_credential(
                        provider=provider,
                        credential=credential,
                    ),
                ),
                payload=payload,
                http_client=http_client,
            )
            if credential is not None:
                await repository.mark_provider_credential_used(
                    provider_credential=credential,
                    db=db,
                )
            return stream
        except ProviderUpstreamError as exc:
            last_error = exc
            if credential is not None:
                await _mark_provider_credential_failed(
                    provider_credential=credential,
                    error=exc,
                    db=db,
                )
            if provider_credential_id is not None or not _should_try_next_credential(exc):
                raise
    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider


async def _get_provider_credential_or_raise(
    *,
    provider_id: UUID,
    provider_credential_id: UUID,
    scope: Scope,
    db: AsyncSession,
):
    provider_credential = await repository.get_provider_credential(
        org_id=scope.org_id,
        provider_credential_id=provider_credential_id,
        db=db,
    )
    if provider_credential is None or provider_credential.provider_id != provider_id:
        raise ProviderNotFoundError
    return provider_credential


async def _get_model_offering_or_raise(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    scope: Scope,
    db: AsyncSession,
):
    model_offering = await repository.get_model_offering(
        org_id=scope.org_id,
        model_offering_id=model_offering_id,
        db=db,
    )
    if model_offering is None or model_offering.provider_id != provider_id:
        raise ProviderNotFoundError
    return model_offering


def _to_response(provider: Provider) -> ProviderResponse:
    return ProviderResponse.model_validate(provider)


async def _resolve_provider_credential_route(
    *,
    provider: Provider,
    provider_credential_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderCredential | None]:
    if provider_credential_id is None:
        provider_credentials = await repository.list_provider_credentials(
            org_id=scope.org_id,
            provider_id=provider.id,
            db=db,
        )
        active_credentials = [
            credential for credential in provider_credentials if credential.is_active
        ]
        if active_credentials:
            return _route_provider_credentials(
                active_credentials,
                routing_policy=_provider_routing_policy(provider),
            )
        if provider.api_key_encrypted is not None:
            return [None]
        raise ProviderCredentialRequiredError

    provider_credential = await repository.get_provider_credential(
        org_id=scope.org_id,
        provider_credential_id=provider_credential_id,
        db=db,
    )
    if (
        provider_credential is None
        or provider_credential.provider_id != provider.id
        or not provider_credential.is_active
    ):
        raise ProviderNotFoundError

    return [provider_credential]


def _route_provider_credentials(
    credentials: list[ProviderCredential],
    *,
    routing_policy: ProviderCredentialRoutingPolicy,
) -> list[ProviderCredential]:
    ordered = sorted(credentials, key=_provider_credential_priority_key)
    if routing_policy == ProviderCredentialRoutingPolicy.priority:
        return [ordered[0]]
    if routing_policy == ProviderCredentialRoutingPolicy.round_robin:
        return [sorted(credentials, key=_provider_credential_lru_key)[0]]
    if routing_policy == ProviderCredentialRoutingPolicy.least_recently_used:
        return [sorted(credentials, key=_provider_credential_lru_key)[0]]
    if routing_policy == ProviderCredentialRoutingPolicy.health_based:
        return [sorted(credentials, key=_provider_credential_health_key)[0]]
    if routing_policy == ProviderCredentialRoutingPolicy.weighted:
        return [_weighted_provider_credential_route(credentials)[0]]
    if routing_policy == ProviderCredentialRoutingPolicy.fallback:
        return ordered
    return ordered


def _provider_routing_policy(provider: Provider) -> ProviderCredentialRoutingPolicy:
    try:
        return ProviderCredentialRoutingPolicy(provider.credential_routing_policy)
    except ValueError:
        return ProviderCredentialRoutingPolicy.priority


def _provider_credential_priority_key(
    credential: ProviderCredential,
) -> tuple[int, datetime]:
    return (credential.priority, credential.created_at)


def _provider_credential_lru_key(
    credential: ProviderCredential,
) -> tuple[datetime, int, datetime]:
    return (
        credential.last_used_at or datetime.min.replace(tzinfo=UTC),
        credential.priority,
        credential.created_at,
    )


def _provider_credential_health_key(
    credential: ProviderCredential,
) -> tuple[int, int, datetime]:
    health_rank = {
        "valid": 0,
        "unchecked": 1,
        "degraded": 2,
        "invalid": 3,
    }.get(credential.health_status, 2)
    return (health_rank, credential.priority, credential.created_at)


def _weighted_provider_credential_route(
    credentials: list[ProviderCredential],
) -> list[ProviderCredential]:
    weighted_pool: list[ProviderCredential] = []
    for credential in credentials:
        weight = max(1, 101 - credential.priority)
        weighted_pool.extend([credential] * weight)
    selected = secrets.choice(weighted_pool)
    rest = [
        credential
        for credential in sorted(credentials, key=_provider_credential_priority_key)
        if credential.id != selected.id
    ]
    return [selected, *rest]


def _api_key_for_routed_credential(
    *,
    provider: Provider,
    credential: ProviderCredential | None,
) -> str:
    if credential is None:
        if provider.api_key_encrypted is None:
            raise ProviderCredentialRequiredError
        return decrypt(provider.api_key_encrypted)
    return decrypt(credential.api_key_encrypted)


async def _mark_provider_credential_failed(
    *,
    provider_credential: ProviderCredential,
    error: ProviderUpstreamError,
    db: AsyncSession,
) -> None:
    provider_credential.health_status = "invalid" if error.status_code in {401, 403} else "degraded"
    provider_credential.last_validation_error = str(error.body)
    await db.flush()


def _should_try_next_credential(error: ProviderUpstreamError) -> bool:
    return error.status_code in {401, 403, 408, 409, 429, 500, 502, 503, 504}


def _key_prefix(api_key: str) -> str:
    return f"{api_key[:4]}..."


def _normalize_api_key(api_key: str) -> str:
    normalized = api_key.strip()
    if normalized.lower().startswith("bearer "):
        normalized = normalized[7:].strip()
    return normalized


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "provider"


def _default_capabilities() -> dict[str, bool]:
    return {
        "chat": True,
        "embeddings": False,
        "vision": False,
        "tools": False,
        "json_mode": False,
        "streaming": True,
    }


def _default_model_capabilities() -> dict[str, bool]:
    return {"chat": True}


def _enrich_model_offering_from_metadata(
    *,
    model_offering: ModelOffering,
    metadata: ModelMetadata,
) -> None:
    model_offering.capabilities = {
        **metadata.capabilities,
        **(model_offering.capabilities or {}),
    }
    if model_offering.context_window is None:
        model_offering.context_window = metadata.context_window
    if model_offering.version is None:
        model_offering.version = metadata.version
    if not model_offering.input_modalities:
        model_offering.input_modalities = metadata.input_modalities
    if not model_offering.output_modalities:
        model_offering.output_modalities = metadata.output_modalities
    if model_offering.modality == "text":
        model_offering.modality = _combined_modality(
            model_offering.input_modalities,
            model_offering.output_modalities,
        )
    if model_offering.input_price_per_million_tokens is None:
        model_offering.input_price_per_million_tokens = (
            metadata.pricing.input_price_per_million_tokens
        )
    if model_offering.output_price_per_million_tokens is None:
        model_offering.output_price_per_million_tokens = (
            metadata.pricing.output_price_per_million_tokens
        )
    if model_offering.cached_input_price_per_million_tokens is None:
        model_offering.cached_input_price_per_million_tokens = (
            metadata.pricing.cached_input_price_per_million_tokens
        )
    model_offering.rate_limit_hints = {
        **metadata.rate_limit_hints,
        **(model_offering.rate_limit_hints or {}),
    }


def _overwrite_model_offering_from_metadata(
    *,
    model_offering: ModelOffering,
    metadata: ModelMetadata,
) -> None:
    model_offering.version = metadata.version
    model_offering.input_modalities = metadata.input_modalities
    model_offering.output_modalities = metadata.output_modalities
    model_offering.modality = _combined_modality(
        metadata.input_modalities,
        metadata.output_modalities,
    )
    model_offering.capabilities = metadata.capabilities
    model_offering.context_window = metadata.context_window
    model_offering.input_price_per_million_tokens = (
        metadata.pricing.input_price_per_million_tokens
    )
    model_offering.output_price_per_million_tokens = (
        metadata.pricing.output_price_per_million_tokens
    )
    model_offering.cached_input_price_per_million_tokens = (
        metadata.pricing.cached_input_price_per_million_tokens
    )
    model_offering.rate_limit_hints = metadata.rate_limit_hints
    model_offering.metadata_source = "catalog"


def _combined_modality(input_modalities: list[str], output_modalities: list[str]) -> str:
    ordered = []
    for modality in [*input_modalities, *output_modalities]:
        normalized = modality.strip().lower()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return "+".join(ordered) or "text"

