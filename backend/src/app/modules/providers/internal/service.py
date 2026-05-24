import asyncio
import re
import secrets
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.core.security import decrypt, encrypt
from app.modules.activity import facade as activity_facade
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
from app.modules.providers.internal.models import (
    CredentialPool,
    CredentialPoolCredential,
    ModelOffering,
    Provider,
    ProviderCredential,
)
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    CredentialPoolCredentialResponse,
    CredentialPoolResponse,
    ModelMetadataSyncMode,
    ModelOfferingPageResponse,
    ModelOfferingResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
    ProviderCredentialResponse,
    ProviderCredentialRoutingPolicy,
    ProviderCredentialSummary,
    ProviderReadiness,
    ProviderResponse,
    TestModelOfferingRequest,
    TestModelOfferingResponse,
    TestProviderCredentialResponse,
    UpdateCredentialPoolCredentialRequest,
    UpdateCredentialPoolRequest,
    UpdateModelOfferingRequest,
    UpdateProviderCredentialRequest,
    UpdateProviderRequest,
)

logger = structlog.get_logger(__name__)

_provider_semaphores: dict[UUID, tuple[int, asyncio.Semaphore]] = {}
_provider_circuit_events: dict[UUID, deque[tuple[datetime, bool]]] = defaultdict(deque)
_provider_circuit_open_until: dict[UUID, datetime] = {}


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
            api_key_encrypted=None,
            adapter_type=OPENAI_COMPAT_ADAPTER,
            description=payload.description,
            capabilities=payload.capabilities or _default_capabilities(),
            request_timeout_seconds=payload.request_timeout_seconds,
            max_body_bytes=payload.max_body_bytes,
            retry_policy=payload.retry_policy,
            fallback_policy=payload.fallback_policy,
            circuit_breaker_policy=payload.circuit_breaker_policy,
            max_concurrent_requests=payload.max_concurrent_requests,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider.created",
            message=f"Created provider {provider.name}.",
            provider_id=provider.id,
            db=db,
        )

    logger.info("provider_created", provider_id=str(provider.id), org_id=str(scope.org_id))
    return _to_response(provider)


async def list_providers(*, scope: Scope, db: AsyncSession) -> list[ProviderResponse]:
    providers = await repository.list_providers(org_id=scope.org_id, db=db)
    credentials = await repository.list_all_provider_credentials(org_id=scope.org_id, db=db)
    summaries = _credential_summaries(credentials)
    await _attach_provider_readiness_data(providers=providers, org_id=scope.org_id, db=db)
    return [_to_response(provider, summaries.get(provider.id)) for provider in providers]


async def get_provider(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> ProviderResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    credentials = await repository.list_provider_credentials(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    await _attach_provider_readiness_data(providers=[provider], org_id=scope.org_id, db=db)
    return _to_response(provider, _credential_summary(credentials))


async def create_credential_pool(
    *,
    provider_id: UUID,
    payload: CreateCredentialPoolRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        pool = await repository.create_credential_pool(
            org_id=scope.org_id,
            provider_id=provider_id,
            name=payload.name,
            description=payload.description,
            selection_policy=payload.selection_policy,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool.created",
            message=f"Created credential pool {pool.name}.",
            provider_id=provider_id,
            pool_id=pool.id,
            db=db,
        )
    logger.info(
        "credential_pool_created",
        provider_id=str(provider_id),
        pool_id=str(pool.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _credential_pool_response(pool)


async def list_credential_pools(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[CredentialPoolResponse]:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    pools = await repository.list_credential_pools(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    counts: dict[UUID, tuple[int, int]] = {}
    for pool in pools:
        rows = await repository.list_pool_credentials(org_id=scope.org_id, pool_id=pool.id, db=db)
        active_count = sum(
            1 for membership, credential in rows if membership.is_active and credential.is_active
        )
        counts[pool.id] = (len(rows), active_count)
    return [
        _credential_pool_response(
            pool,
            credential_count=counts.get(pool.id, (0, 0))[0],
            active_credential_count=counts.get(pool.id, (0, 0))[1],
        )
        for pool in pools
    ]


async def get_credential_pool(
    *,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    pool = await repository.get_credential_pool(
        org_id=scope.org_id,
        pool_id=pool_id,
        db=db,
    )
    if pool is None:
        raise ProviderNotFoundError
    return _credential_pool_response(pool)


async def update_credential_pool(
    *,
    provider_id: UUID,
    pool_id: UUID,
    payload: UpdateCredentialPoolRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        pool = await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        if payload.name is not None:
            pool.name = payload.name
        if "description" in payload.model_fields_set:
            pool.description = payload.description
        if payload.selection_policy is not None:
            pool.selection_policy = payload.selection_policy
        if payload.is_active is not None:
            pool.is_active = payload.is_active
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool.updated",
            message=f"Updated credential pool {pool.name}.",
            provider_id=provider_id,
            pool_id=pool.id,
            db=db,
        )
    logger.info(
        "credential_pool_updated",
        provider_id=str(provider_id),
        pool_id=str(pool.id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _credential_pool_response(pool)


async def list_credential_pool_credentials(
    *,
    provider_id: UUID,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> list[CredentialPoolCredentialResponse]:
    await _get_credential_pool_or_raise(
        provider_id=provider_id,
        pool_id=pool_id,
        scope=scope,
        db=db,
    )
    rows = await repository.list_pool_credentials(
        org_id=scope.org_id,
        pool_id=pool_id,
        db=db,
    )
    return [_pool_credential_response(membership, credential) for membership, credential in rows]


async def add_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    payload: AddCredentialPoolCredentialRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPoolCredentialResponse:
    async with transaction(db):
        await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=payload.provider_credential_id,
            scope=scope,
            db=db,
        )
        membership = await repository.create_pool_credential(
            org_id=scope.org_id,
            pool_id=pool_id,
            provider_credential_id=payload.provider_credential_id,
            priority=payload.priority,
            weight=payload.weight,
            is_active=payload.is_active,
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool_credential.added",
            message=f"Added credential {credential.name} to credential pool.",
            provider_id=provider_id,
            pool_id=pool_id,
            metadata={"provider_credential_id": str(payload.provider_credential_id)},
            db=db,
        )
    logger.info(
        "credential_pool_credential_added",
        provider_id=str(provider_id),
        pool_id=str(pool_id),
        provider_credential_id=str(payload.provider_credential_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _pool_credential_response(membership, credential)


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
    async with transaction(db):
        await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        membership = await repository.get_pool_credential(
            org_id=scope.org_id,
            pool_credential_id=pool_credential_id,
            db=db,
        )
        if membership is None or membership.pool_id != pool_id:
            raise ProviderNotFoundError
        if payload.priority is not None:
            membership.priority = payload.priority
        if payload.weight is not None:
            membership.weight = payload.weight
        if payload.is_active is not None:
            membership.is_active = payload.is_active
        credential = await _get_provider_credential_or_raise(
            provider_id=provider_id,
            provider_credential_id=membership.provider_credential_id,
            scope=scope,
            db=db,
        )
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool_credential.updated",
            message=f"Updated pool membership for credential {credential.name}.",
            provider_id=provider_id,
            pool_id=pool_id,
            metadata={"pool_credential_id": str(pool_credential_id)},
            db=db,
        )
    logger.info(
        "credential_pool_credential_updated",
        provider_id=str(provider_id),
        pool_id=str(pool_id),
        pool_credential_id=str(pool_credential_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )
    return _pool_credential_response(membership, credential)


async def delete_credential_pool_credential(
    *,
    provider_id: UUID,
    pool_id: UUID,
    pool_credential_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _get_credential_pool_or_raise(
            provider_id=provider_id,
            pool_id=pool_id,
            scope=scope,
            db=db,
        )
        membership = await repository.get_pool_credential(
            org_id=scope.org_id,
            pool_credential_id=pool_credential_id,
            db=db,
        )
        if membership is None or membership.pool_id != pool_id:
            raise ProviderNotFoundError
        await repository.delete_pool_credential(pool_credential=membership, db=db)
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="credential_pool_credential.removed",
            message="Removed credential from credential pool.",
            provider_id=provider_id,
            pool_id=pool_id,
            metadata={"pool_credential_id": str(pool_credential_id)},
            db=db,
        )
    logger.info(
        "credential_pool_credential_deleted",
        provider_id=str(provider_id),
        pool_id=str(pool_id),
        pool_credential_id=str(pool_credential_id),
        org_id=str(scope.org_id),
        actor_user_id=str(actor.id),
    )


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
            db=db,
        )
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider_credential.created",
            message=f"Created provider credential {provider_credential.name}.",
            provider_id=provider_id,
            metadata={"provider_credential_id": str(provider_credential.id)},
            db=db,
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
        if payload.name is not None:
            provider_credential.name = payload.name
        if payload.api_key is not None:
            api_key = _normalize_api_key(payload.api_key)
            provider_credential.key_prefix = _key_prefix(api_key)
            provider_credential.api_key_encrypted = encrypt(api_key)
            provider_credential.health_status = "unchecked"
            provider_credential.last_validation_error = None
        if payload.is_active is not None:
            provider_credential.is_active = payload.is_active

        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider_credential.updated",
            message=f"Updated provider credential {provider_credential.name}.",
            provider_id=provider_id,
            metadata={"provider_credential_id": str(provider_credential.id)},
            db=db,
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
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider_credential.deactivated",
            message=f"Deactivated provider credential {provider_credential.name}.",
            provider_id=provider_id,
            metadata={"provider_credential_id": str(provider_credential.id)},
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
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="model_offering.created",
            message=f"Created model offering {model_offering.provider_model_name}.",
            provider_id=provider_id,
            model_offering_id=model_offering.id,
            db=db,
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
    sync_mode: str,
) -> list[ModelOfferingResponse]:
    if sync_mode == "disabled":
        raise ProviderUpstreamError(status_code=409, body={"error": "model sync is disabled"})
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
        synced_names = set(model_names)
        if sync_mode == "replace":
            existing_models, _ = await repository.list_model_offerings(
                org_id=scope.org_id,
                provider_id=provider_id,
                search=None,
                modalities=None,
                is_active=None,
                limit=10_000,
                offset=0,
                db=db,
            )
            for existing_model in existing_models:
                if existing_model.provider_model_name not in synced_names:
                    existing_model.is_active = False
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
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="model_offerings.synced",
            message=f"Synced {len(synced_models)} model offerings.",
            provider_id=provider_id,
            metadata={"model_count": len(synced_models)},
            db=db,
        )

    logger.info(
        "model_offerings_synced",
        provider_id=str(provider_id),
        model_count=len(synced_models),
        org_id=str(scope.org_id),
    )
    return [
        ModelOfferingResponse.model_validate(model_offering) for model_offering in synced_models
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


async def test_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    payload: TestModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> TestModelOfferingResponse:
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        model_offering = await _get_model_offering_or_raise(
            provider_id=provider_id,
            model_offering_id=model_offering_id,
            scope=scope,
            db=db,
        )
        if not provider.is_active or not model_offering.is_active:
            raise ProviderNotFoundError

        adapter = default_adapter_registry.get(provider.adapter_type)
        routed_credentials = await _resolve_provider_credential_route(
            provider=provider,
            provider_credential_id=payload.provider_credential_id,
            scope=scope,
            db=db,
        )
        tested_credential_id: UUID | None = None
        health_status = "invalid"
        error: str | None = None
        upstream_status_code: int | None = None
        last_error: ProviderUpstreamError | None = None

        for credential in routed_credentials:
            tested_credential_id = credential.id if credential is not None else None
            try:
                response = await adapter.create_chat_completion(
                    provider=AdapterProvider(
                        base_url=provider.base_url,
                        api_key=_api_key_for_routed_credential(
                            provider=provider,
                            credential=credential,
                        ),
                    ),
                    payload=ProviderChatCompletionRequest(
                        model=model_offering.provider_model_name,
                        messages=[
                            {
                                "role": "user",
                                "content": "Reply with ok.",
                            }
                        ],
                    ),
                    http_client=http_client,
                )
                upstream_status_code = response.status_code
                health_status = "valid"
                error = None
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                break
            except ProviderUpstreamError as exc:
                last_error = exc
                upstream_status_code = exc.status_code
                error = str(exc.body)
                if credential is not None:
                    await _mark_provider_credential_failed(
                        provider_credential=credential,
                        error=exc,
                        db=db,
                    )
                if payload.provider_credential_id is not None or not _should_try_next_credential(
                    exc
                ):
                    break
            except Exception as exc:  # noqa: BLE001 - surfaced as model validation result.
                error = str(exc)
                break

        if last_error is not None and error is None:
            error = str(last_error.body)

    return TestModelOfferingResponse(
        id=model_offering.id,
        provider_credential_id=tested_credential_id,
        health_status=health_status,
        last_validation_error=error,
        upstream_status_code=upstream_status_code,
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
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="model_offering.updated",
            message=f"Updated model offering {model_offering.provider_model_name}.",
            provider_id=provider_id,
            model_offering_id=model_offering.id,
            db=db,
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
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="model_offering.deactivated",
            message=f"Deactivated model offering {model_offering.provider_model_name}.",
            provider_id=provider_id,
            model_offering_id=model_offering.id,
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
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
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
        if payload.is_active is not None:
            provider.is_active = payload.is_active
        await db.flush()
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider.updated",
            message=f"Updated provider {provider.name}.",
            provider_id=provider.id,
            db=db,
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
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="provider.deactivated",
            message=f"Deactivated provider {provider.name}.",
            provider_id=provider.id,
            db=db,
        )

    logger.info("provider_deactivated", provider_id=str(provider_id), org_id=str(scope.org_id))


async def create_chat_completion(
    *,
    provider_id: UUID,
    pool_id: UUID | None = None,
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionResponse:
    return await _create_chat_completion_with_policy(
        provider_id=provider_id,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        payload=payload,
        scope=scope,
        db=db,
        http_client=http_client,
        allow_provider_fallback=True,
    )


async def _create_chat_completion_with_policy(
    *,
    provider_id: UUID,
    pool_id: UUID | None,
    provider_credential_id: UUID | None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    allow_provider_fallback: bool,
) -> ProviderChatCompletionResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError

    _raise_if_circuit_open(provider)
    adapter = default_adapter_registry.get(provider.adapter_type)
    routed_credentials = await _resolve_provider_credential_route(
        provider=provider,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    last_error: ProviderUpstreamError | None = None
    async with _provider_concurrency_slot(provider):
        for credential in routed_credentials:

            async def call_upstream(
                routed_credential: ProviderCredential | None = credential,
            ) -> ProviderChatCompletionResponse:
                return await adapter.create_chat_completion(
                    provider=AdapterProvider(
                        base_url=provider.base_url,
                        api_key=_api_key_for_routed_credential(
                            provider=provider,
                            credential=routed_credential,
                        ),
                    ),
                    payload=payload,
                    http_client=http_client,
                )

            try:
                response = await _call_with_retries(
                    call=call_upstream,
                    provider=provider,
                )
                _record_circuit_success(provider)
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                return response
            except ProviderUpstreamError as exc:
                last_error = exc
                _record_circuit_failure(provider)
                if credential is not None:
                    await _mark_provider_credential_failed(
                        provider_credential=credential,
                        error=exc,
                        db=db,
                    )
                if provider_credential_id is not None or not _should_try_next_credential(exc):
                    break

    if allow_provider_fallback and provider_credential_id is None and last_error is not None:
        fallback_result = await _try_provider_fallbacks(
            provider=provider,
            payload=payload,
            scope=scope,
            db=db,
            http_client=http_client,
        )
        if isinstance(fallback_result, ProviderChatCompletionResponse):
            return fallback_result
        if isinstance(fallback_result, ProviderUpstreamError):
            last_error = fallback_result

    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


async def _try_provider_fallbacks(
    *,
    provider: Provider,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderChatCompletionResponse | ProviderUpstreamError | None:
    fallback_policy = _fallback_policy(provider)
    if not fallback_policy["enabled"]:
        return None
    fallback_ids = fallback_policy["fallback_provider_ids"]
    if not fallback_ids:
        return None

    last_error: ProviderUpstreamError | None = None
    for fallback_provider_id in fallback_ids:
        try:
            return await _create_chat_completion_with_policy(
                provider_id=fallback_provider_id,
                pool_id=None,
                provider_credential_id=None,
                payload=payload,
                scope=scope,
                db=db,
                http_client=http_client,
                allow_provider_fallback=False,
            )
        except ProviderUpstreamError as exc:
            last_error = exc
            if exc.status_code not in fallback_policy["trigger_on_status"]:
                return exc
        except (ProviderInactiveError, ProviderCredentialRequiredError):
            continue
    return last_error


async def _call_with_retries(
    *,
    call: Callable[[], Awaitable[ProviderChatCompletionResponse]],
    provider: Provider,
) -> ProviderChatCompletionResponse:
    retry_policy = _retry_policy(provider)
    max_attempts = retry_policy["max_attempts"] if retry_policy["enabled"] else 1
    last_error: ProviderUpstreamError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with asyncio.timeout(provider.request_timeout_seconds):
                return await call()
        except TimeoutError as exc:
            last_error = ProviderUpstreamError(
                status_code=504,
                body={"error": "provider request timed out"},
            )
            if attempt >= max_attempts or 504 not in retry_policy["retry_on_status"]:
                raise last_error from exc
        except ProviderUpstreamError as exc:
            last_error = exc
            if attempt >= max_attempts or exc.status_code not in retry_policy["retry_on_status"]:
                raise
        await asyncio.sleep(_retry_delay_seconds(retry_policy, attempt))
    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


def _retry_delay_seconds(policy: dict, attempt: int) -> float:
    initial = policy["initial_delay_ms"] / 1000
    maximum = policy["max_delay_ms"] / 1000
    if policy["backoff"] == "constant":
        return min(initial, maximum)
    if policy["backoff"] == "linear":
        return min(initial * attempt, maximum)
    return min(initial * (2 ** (attempt - 1)), maximum)


def _retry_policy(provider: Provider) -> dict:
    stored = provider.retry_policy if isinstance(provider.retry_policy, dict) else {}
    return {
        "enabled": bool(stored.get("enabled", False)),
        "max_attempts": _int_policy_value(stored.get("max_attempts"), 3, minimum=1, maximum=10),
        "backoff": (
            stored.get("backoff")
            if stored.get("backoff") in {"constant", "linear", "exponential"}
            else "exponential"
        ),
        "initial_delay_ms": _int_policy_value(
            stored.get("initial_delay_ms"),
            500,
            minimum=0,
        ),
        "max_delay_ms": _int_policy_value(stored.get("max_delay_ms"), 10000, minimum=0),
        "retry_on_status": _status_policy_values(
            stored.get("retry_on_status"),
            fallback={408, 429, 500, 502, 503, 504},
        ),
    }


def _fallback_policy(provider: Provider) -> dict:
    stored = provider.fallback_policy if isinstance(provider.fallback_policy, dict) else {}
    fallback_ids = []
    if isinstance(stored.get("fallback_provider_ids"), list):
        for item in stored["fallback_provider_ids"]:
            try:
                fallback_ids.append(UUID(str(item)))
            except ValueError:
                continue
    return {
        "enabled": bool(stored.get("enabled", False)),
        "trigger_on_status": _status_policy_values(
            stored.get("trigger_on_status"),
            fallback={502, 503, 504},
        ),
        "fallback_provider_ids": fallback_ids,
    }


def _circuit_breaker_policy(provider: Provider) -> dict:
    stored = (
        provider.circuit_breaker_policy if isinstance(provider.circuit_breaker_policy, dict) else {}
    )
    return {
        "enabled": bool(stored.get("enabled", False)),
        "failure_threshold_pct": _int_policy_value(
            stored.get("failure_threshold_pct"),
            50,
            minimum=0,
            maximum=100,
        ),
        "min_request_count": _int_policy_value(stored.get("min_request_count"), 20, minimum=0),
        "window_seconds": _int_policy_value(stored.get("window_seconds"), 60, minimum=1),
        "cooldown_seconds": _int_policy_value(stored.get("cooldown_seconds"), 30, minimum=1),
    }


def _raise_if_circuit_open(provider: Provider) -> None:
    policy = _circuit_breaker_policy(provider)
    if not policy["enabled"]:
        return
    now = datetime.now(UTC)
    open_until = _provider_circuit_open_until.get(provider.id)
    if open_until and open_until > now:
        raise ProviderUpstreamError(status_code=503, body={"error": "provider circuit is open"})
    if open_until:
        _provider_circuit_open_until.pop(provider.id, None)


def _record_circuit_success(provider: Provider) -> None:
    policy = _circuit_breaker_policy(provider)
    if not policy["enabled"]:
        return
    _record_circuit_event(provider, succeeded=True, policy=policy)
    _provider_circuit_open_until.pop(provider.id, None)


def _record_circuit_failure(provider: Provider) -> None:
    policy = _circuit_breaker_policy(provider)
    if not policy["enabled"]:
        return
    now = datetime.now(UTC)
    events = _record_circuit_event(provider, succeeded=False, policy=policy, now=now)
    if len(events) < policy["min_request_count"]:
        return
    failure_count = sum(1 for _, succeeded in events if not succeeded)
    failure_pct = int((failure_count / len(events)) * 100)
    if failure_pct < policy["failure_threshold_pct"]:
        return
    _provider_circuit_open_until[provider.id] = now + timedelta(
        seconds=policy["cooldown_seconds"],
    )


def _record_circuit_event(
    provider: Provider,
    *,
    succeeded: bool,
    policy: dict,
    now: datetime | None = None,
) -> deque[tuple[datetime, bool]]:
    recorded_at = now or datetime.now(UTC)
    events = _provider_circuit_events[provider.id]
    events.append((recorded_at, succeeded))
    window_started_at = recorded_at.timestamp() - policy["window_seconds"]
    while events and events[0][0].timestamp() < window_started_at:
        events.popleft()
    return events


def _provider_concurrency_slot(provider: Provider):
    if provider.max_concurrent_requests is None:
        return _NoopAsyncContext()
    stored = _provider_semaphores.get(provider.id)
    if stored is None or stored[0] != provider.max_concurrent_requests:
        semaphore = asyncio.Semaphore(provider.max_concurrent_requests)
        _provider_semaphores[provider.id] = (provider.max_concurrent_requests, semaphore)
        return semaphore
    _, semaphore = stored
    return semaphore


class _NoopAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _int_policy_value(
    value: object,
    fallback: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = fallback
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _status_policy_values(value: object, *, fallback: set[int]) -> set[int]:
    if not isinstance(value, list):
        return set(fallback)
    statuses = set()
    for item in value:
        try:
            status_code = int(item)
        except (TypeError, ValueError):
            continue
        if 100 <= status_code <= 599:
            statuses.add(status_code)
    return statuses or set(fallback)


async def stream_chat_completion(
    *,
    provider_id: UUID,
    pool_id: UUID | None = None,
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
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    last_error: ProviderUpstreamError | None = None
    _raise_if_circuit_open(provider)
    async with _provider_concurrency_slot(provider):
        for credential in routed_credentials:
            try:
                async with asyncio.timeout(provider.request_timeout_seconds):
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
                _record_circuit_success(provider)
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                return stream
            except TimeoutError as exc:
                last_error = ProviderUpstreamError(
                    status_code=504,
                    body={"error": "provider request timed out"},
                )
                _record_circuit_failure(provider)
                if credential is not None:
                    await _mark_provider_credential_failed(
                        provider_credential=credential,
                        error=last_error,
                        db=db,
                    )
                if provider_credential_id is not None:
                    raise last_error from exc
            except ProviderUpstreamError as exc:
                last_error = exc
                _record_circuit_failure(provider)
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


async def _get_credential_pool_or_raise(
    *,
    provider_id: UUID,
    pool_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> CredentialPool:
    pool = await repository.get_credential_pool(
        org_id=scope.org_id,
        pool_id=pool_id,
        db=db,
    )
    if pool is None or pool.provider_id != provider_id:
        raise ProviderNotFoundError
    return pool


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


def _to_response(
    provider: Provider,
    credential_summary: ProviderCredentialSummary | None = None,
) -> ProviderResponse:
    response = ProviderResponse.model_validate(provider)
    response.credential_summary = credential_summary or ProviderCredentialSummary()
    response.catalog_type = _provider_catalog_type(provider)
    response.capabilities = _aggregate_provider_capabilities(provider)
    response.readiness = _provider_readiness(provider, response.credential_summary)
    return response


async def _attach_provider_readiness_data(
    *,
    providers: list[Provider],
    org_id: UUID,
    db: AsyncSession,
) -> None:
    if not providers:
        return
    capabilities_by_provider = await repository.list_active_model_capabilities_by_provider(
        org_id=org_id,
        db=db,
    )
    model_counts_by_provider = await repository.list_active_model_counts_by_provider(
        org_id=org_id,
        db=db,
    )
    pool_readiness_by_provider = await repository.list_pool_readiness_by_provider(
        org_id=org_id,
        db=db,
    )
    for provider in providers:
        provider._active_model_capabilities = capabilities_by_provider.get(provider.id, [])
        provider._active_model_count = model_counts_by_provider.get(provider.id, 0)
        provider._pool_summary = pool_readiness_by_provider.get(provider.id, {})


def _provider_catalog_type(provider: Provider) -> str:
    return "default" if provider.supported_integration == "openai_compatible_default" else "custom"


def _aggregate_provider_capabilities(provider: Provider) -> dict:
    model_capabilities = getattr(provider, "_active_model_capabilities", None)
    if not model_capabilities:
        return {}
    aggregate: dict[str, bool] = {}
    for capabilities in model_capabilities:
        if not isinstance(capabilities, dict):
            continue
        for key, value in capabilities.items():
            if isinstance(value, bool):
                aggregate[key] = aggregate.get(key, False) or value
    return aggregate


def _provider_readiness(
    provider: Provider,
    credential_summary: ProviderCredentialSummary,
) -> ProviderReadiness:
    pool_summary = getattr(provider, "_pool_summary", {})
    active_pool_count = int(pool_summary.get("active_pool_count", 0))
    active_pool_credential_count = int(pool_summary.get("active_pool_credential_count", 0))
    active_model_count = int(getattr(provider, "_active_model_count", 0) or 0)
    return ProviderReadiness(
        has_active_provider=provider.is_active,
        has_active_credential=credential_summary.active > 0,
        has_active_pool=active_pool_count > 0,
        has_active_pool_credential=active_pool_credential_count > 0,
        has_active_model=active_model_count > 0,
        is_ready=all(
            [
                provider.is_active,
                credential_summary.active > 0,
                active_pool_count > 0,
                active_pool_credential_count > 0,
                active_model_count > 0,
            ]
        ),
    )


def _credential_summaries(
    credentials: list[ProviderCredential],
) -> dict[UUID, ProviderCredentialSummary]:
    grouped: dict[UUID, list[ProviderCredential]] = defaultdict(list)
    for credential in credentials:
        grouped[credential.provider_id].append(credential)
    return {
        provider_id: _credential_summary(provider_credentials)
        for provider_id, provider_credentials in grouped.items()
    }


def _credential_summary(credentials: list[ProviderCredential]) -> ProviderCredentialSummary:
    summary = ProviderCredentialSummary(total=len(credentials))
    for credential in credentials:
        if credential.is_active:
            summary.active += 1
        status = credential.health_status if credential.health_status else "unchecked"
        if status == "valid":
            summary.valid += 1
        elif status == "degraded":
            summary.degraded += 1
        elif status == "invalid":
            summary.invalid += 1
        else:
            summary.unchecked += 1
    return summary


def _credential_pool_response(
    pool: CredentialPool,
    *,
    credential_count: int = 0,
    active_credential_count: int = 0,
) -> CredentialPoolResponse:
    return CredentialPoolResponse(
        id=pool.id,
        org_id=pool.org_id,
        provider_id=pool.provider_id,
        name=pool.name,
        description=pool.description,
        selection_policy=pool.selection_policy,
        is_active=pool.is_active,
        credential_count=credential_count,
        active_credential_count=active_credential_count,
        created_at=pool.created_at,
        updated_at=pool.updated_at,
    )


def _pool_credential_response(
    membership: CredentialPoolCredential,
    credential: ProviderCredential,
) -> CredentialPoolCredentialResponse:
    return CredentialPoolCredentialResponse(
        id=membership.id,
        org_id=membership.org_id,
        pool_id=membership.pool_id,
        provider_credential_id=membership.provider_credential_id,
        priority=membership.priority,
        weight=membership.weight,
        is_active=membership.is_active,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
        credential=ProviderCredentialResponse.model_validate(credential),
    )


async def _resolve_provider_credential_route(
    *,
    provider: Provider,
    pool_id: UUID | None = None,
    provider_credential_id: UUID | None = None,
    scope: Scope,
    db: AsyncSession,
) -> list[ProviderCredential | None]:
    if provider_credential_id is None:
        if pool_id is not None:
            pool = await _get_credential_pool_or_raise(
                provider_id=provider.id,
                pool_id=pool_id,
                scope=scope,
                db=db,
            )
            if not pool.is_active:
                raise ProviderCredentialRequiredError
            pool_credentials = await repository.list_pool_credentials(
                org_id=scope.org_id,
                pool_id=pool_id,
                db=db,
            )
            routing_policy = ProviderCredentialRoutingPolicy(pool.selection_policy)
            active_pool_credentials = [
                (membership, credential)
                for membership, credential in pool_credentials
                if membership.is_active and credential.is_active
            ]
            if active_pool_credentials:
                return _route_pool_credentials(
                    active_pool_credentials,
                    routing_policy=routing_policy,
                )
            raise ProviderCredentialRequiredError
        else:
            provider_credentials = await repository.list_provider_credentials(
                org_id=scope.org_id,
                provider_id=provider.id,
                db=db,
            )
            active_credentials = [
                credential for credential in provider_credentials if credential.is_active
            ]
            if active_credentials:
                return sorted(active_credentials, key=lambda credential: credential.created_at)
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


def _route_pool_credentials(
    pool_credentials: list[tuple[CredentialPoolCredential, ProviderCredential]],
    *,
    routing_policy: ProviderCredentialRoutingPolicy,
) -> list[ProviderCredential]:
    ordered = sorted(pool_credentials, key=_pool_credential_priority_key)
    if routing_policy == ProviderCredentialRoutingPolicy.priority:
        return [ordered[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.round_robin:
        return [sorted(pool_credentials, key=_pool_credential_lru_key)[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.least_recently_used:
        return [sorted(pool_credentials, key=_pool_credential_lru_key)[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.health_based:
        return [sorted(pool_credentials, key=_pool_credential_health_key)[0][1]]
    if routing_policy == ProviderCredentialRoutingPolicy.weighted:
        return [_weighted_pool_credential_route(pool_credentials)[0]]
    if routing_policy == ProviderCredentialRoutingPolicy.fallback:
        return [credential for _, credential in ordered]
    return [credential for _, credential in ordered]


def _pool_credential_priority_key(
    item: tuple[CredentialPoolCredential, ProviderCredential],
) -> tuple[int, datetime]:
    membership, credential = item
    return (membership.priority, membership.created_at, credential.created_at)


def _pool_credential_lru_key(
    item: tuple[CredentialPoolCredential, ProviderCredential],
) -> tuple[datetime, int, datetime]:
    membership, credential = item
    return (
        credential.last_used_at or datetime.min.replace(tzinfo=UTC),
        membership.priority,
        credential.created_at,
    )


def _pool_credential_health_key(
    item: tuple[CredentialPoolCredential, ProviderCredential],
) -> tuple[int, int, datetime]:
    membership, credential = item
    health_rank = {
        "valid": 0,
        "unchecked": 1,
        "degraded": 2,
        "invalid": 3,
    }.get(credential.health_status, 2)
    return (health_rank, membership.priority, credential.created_at)


def _weighted_pool_credential_route(
    pool_credentials: list[tuple[CredentialPoolCredential, ProviderCredential]],
) -> list[ProviderCredential]:
    weighted_pool: list[tuple[CredentialPoolCredential, ProviderCredential]] = []
    for item in pool_credentials:
        membership, _credential = item
        weighted_pool.extend([item] * max(1, membership.weight))
    selected_membership, selected = secrets.choice(weighted_pool)
    rest = [
        credential
        for membership, credential in sorted(pool_credentials, key=_pool_credential_priority_key)
        if membership.id != selected_membership.id
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
    model_offering.input_price_per_million_tokens = metadata.pricing.input_price_per_million_tokens
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
