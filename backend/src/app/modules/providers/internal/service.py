import asyncio
import re
import secrets
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.errors import (
    ProviderAdapterNotFoundError,
    ProviderCredentialRequiredError,
    ProviderInactiveError,
    ProviderNotFoundError,
    ProviderResourceConflictError,
    ProviderSlugConflictError,
    ProviderUpstreamError,
)
from app.modules.providers.internal import impact as impact_repository
from app.modules.providers.internal import repository
from app.modules.providers.internal.adapters import (
    ANTHROPIC_VERSION,
    OPENAI_COMPAT_ADAPTER,
    OPENAI_COMPAT_INTEGRATIONS,
    AdapterProvider,
    anthropic_messages_adapter,
    default_adapter_registry,
    default_integration_adapter_registry,
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
from app.modules.providers.internal.secret_backends import (
    LOCAL_SECRET_BACKEND,
    ProviderSecretBackendRegistry,
    get_default_secret_backend_registry,
    resolve_legacy_provider_secret,
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
    ModelSyncSummary,
    ProviderAnthropicMessagesRequest,
    ProviderAnthropicMessagesResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
    ProviderCredentialResponse,
    ProviderCredentialRoutingPolicy,
    ProviderCredentialSummary,
    ProviderImpactResponse,
    ProviderOperationalState,
    ProviderReadiness,
    ProviderResourceImpactResponse,
    ProviderResponse,
    SyncModelOfferingsResponse,
    TestModelOfferingRequest,
    TestModelOfferingResponse,
    TestProviderCredentialResponse,
    UpdateCredentialPoolCredentialRequest,
    UpdateCredentialPoolRequest,
    UpdateModelOfferingRequest,
    UpdateProviderCredentialRequest,
    UpdateProviderRequest,
)
from app.modules.settings import facade as settings_facade

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
    slug = _slugify(payload.slug or payload.name)
    if await repository.get_provider_by_slug(slug=slug, org_id=scope.org_id, db=db):
        raise ProviderSlugConflictError
    async with transaction(db):
        provider = await repository.create_provider(
            org_id=scope.org_id,
            name=payload.name,
            slug=slug,
            base_url=str(payload.base_url).rstrip("/"),
            api_key_encrypted=None,
            adapter_type=OPENAI_COMPAT_ADAPTER,
            description=payload.description,
            capabilities=payload.capabilities.model_dump(),
            request_timeout_seconds=payload.request_timeout_seconds,
            max_body_bytes=payload.max_body_bytes,
            retry_policy=payload.retry_policy.model_dump() if payload.retry_policy else None,
            model_sync_mode=payload.model_sync_mode,
            circuit_breaker_policy=payload.circuit_breaker_policy.model_dump(),
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
    _attach_active_credential_health(providers=providers, credentials=credentials)
    await _attach_provider_readiness_data(providers=providers, org_id=scope.org_id, db=db)
    return [_to_response(provider, summaries.get(provider.id)) for provider in providers]


async def get_provider(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> ProviderResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    credentials = await repository.list_provider_credentials(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )
    _attach_active_credential_health(providers=[provider], credentials=credentials)
    await _attach_provider_readiness_data(providers=[provider], org_id=scope.org_id, db=db)
    return _to_response(provider, _credential_summary(credentials))


async def get_provider_impact(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ProviderImpactResponse:
    await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    return await impact_repository.get_provider_impact(
        org_id=scope.org_id,
        provider_id=provider_id,
        db=db,
    )


async def get_provider_credential_impact(
    *, provider_id: UUID, provider_credential_id: UUID, scope: Scope, db: AsyncSession
) -> ProviderResourceImpactResponse:
    credential = await _get_provider_credential_or_raise(
        provider_id=provider_id, provider_credential_id=provider_credential_id, scope=scope, db=db
    )
    return await impact_repository.get_credential_impact(
        org_id=scope.org_id, credential=credential, db=db
    )


async def get_credential_pool_impact(
    *, provider_id: UUID, pool_id: UUID, scope: Scope, db: AsyncSession
) -> ProviderResourceImpactResponse:
    pool = await _get_credential_pool_or_raise(
        provider_id=provider_id, pool_id=pool_id, scope=scope, db=db
    )
    return await impact_repository.get_pool_impact(org_id=scope.org_id, pool=pool, db=db)


async def get_model_offering_impact(
    *, provider_id: UUID, model_offering_id: UUID, scope: Scope, db: AsyncSession
) -> ProviderResourceImpactResponse:
    model = await _get_model_offering_or_raise(
        provider_id=provider_id, model_offering_id=model_offering_id, scope=scope, db=db
    )
    return await impact_repository.get_model_impact(org_id=scope.org_id, model=model, db=db)


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
        existing_memberships = await repository.list_pool_credentials(
            org_id=scope.org_id,
            pool_id=pool_id,
            db=db,
        )
        if any(
            membership.provider_credential_id == payload.provider_credential_id
            for membership, _credential in existing_memberships
        ):
            raise ProviderResourceConflictError
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
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderCredentialResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        api_key = _normalize_api_key(payload.api_key)
        provider_credential_id = uuid4()
        registry = secret_registry or get_default_secret_backend_registry()
        backend = registry.get(LOCAL_SECRET_BACKEND)
        stored_secret = await backend.store(
            credential_id=provider_credential_id,
            plaintext=api_key,
        )
        provider_credential = await repository.create_provider_credential(
            provider_credential_id=provider_credential_id,
            org_id=scope.org_id,
            provider_id=provider_id,
            created_by=actor.id,
            name=payload.name,
            key_prefix=_key_prefix(api_key),
            api_key_encrypted=stored_secret.storage_value,
            secret_backend=stored_secret.backend,
            secret_reference=stored_secret.reference,
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
    secret_registry: ProviderSecretBackendRegistry | None = None,
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
            registry = secret_registry or get_default_secret_backend_registry()
            backend = registry.get(provider_credential.secret_backend)
            stored_secret = await backend.update(
                credential=provider_credential,
                plaintext=api_key,
            )
            provider_credential.key_prefix = _key_prefix(api_key)
            provider_credential.api_key_encrypted = stored_secret.storage_value
            provider_credential.secret_backend = stored_secret.backend
            provider_credential.secret_reference = stored_secret.reference
            provider_credential.health_status = "unchecked"
            provider_credential.last_validation_error = None
            provider_credential.last_validation_at = None
            provider_credential.last_failure_at = None
            provider_credential.failure_reason = None
            provider_credential.failure_message = None
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
    secret_registry: ProviderSecretBackendRegistry | None = None,
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
            adapter = default_integration_adapter_registry.get(provider.supported_integration)
            await adapter.list_models(
                provider=AdapterProvider(
                    base_url=provider.base_url,
                    api_key=await (
                        secret_registry or get_default_secret_backend_registry()
                    ).resolve(credential=provider_credential),
                ),
                http_client=http_client,
            )
            validated_at = repository.datetime_now()
            provider_credential.health_status = "valid"
            provider_credential.last_validation_error = None
            provider_credential.last_validation_at = validated_at
            provider_credential.last_successful_request_at = validated_at
            provider_credential.failure_reason = None
            provider_credential.failure_message = None
            health_status = "valid"
            error = None
            last_successful_request_at = provider_credential.last_successful_request_at
        except Exception as exc:  # noqa: BLE001 - persisted as upstream credential health.
            validated_at = repository.datetime_now()
            failure_reason, failure_message = _credential_failure_details(exc)
            provider_credential.health_status = "invalid"
            provider_credential.last_validation_error = failure_message
            provider_credential.last_validation_at = validated_at
            provider_credential.last_failure_at = validated_at
            provider_credential.failure_reason = failure_reason
            provider_credential.failure_message = failure_message
            health_status = "invalid"
            error = failure_message
            last_successful_request_at = provider_credential.last_successful_request_at
        await db.flush()

    return TestProviderCredentialResponse(
        id=provider_credential.id,
        health_status=health_status,
        last_validation_error=error,
        last_validation_at=provider_credential.last_validation_at,
        last_successful_request_at=last_successful_request_at,
        last_failure_at=provider_credential.last_failure_at,
        failure_reason=provider_credential.failure_reason,
        failure_message=provider_credential.failure_message,
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
        await _ensure_model_offering_unique(
            org_id=scope.org_id,
            provider_id=provider_id,
            provider_model_name=payload.provider_model_name,
            alias=payload.alias,
            db=db,
        )
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
    return _model_offering_response(model_offering)


async def _ensure_model_offering_unique(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model_name: str | None,
    alias: str | None,
    db: AsyncSession,
    current_model_offering_id: UUID | None = None,
) -> None:
    if provider_model_name is not None:
        existing = await repository.get_model_offering_by_name(
            org_id=org_id,
            provider_id=provider_id,
            provider_model_name=provider_model_name,
            db=db,
        )
        if existing is not None and existing.id != current_model_offering_id:
            raise ProviderResourceConflictError
    if alias is not None:
        # Aliases must be unique across the whole org (not just within a provider): the
        # gateway resolves requested_model against any offering's alias, so a duplicate
        # alias on another provider would make routing ambiguous.
        existing = await repository.get_model_offering_by_alias_in_org(
            org_id=org_id,
            alias=alias,
            db=db,
        )
        if existing is not None and existing.id != current_model_offering_id:
            raise ProviderResourceConflictError


async def sync_model_offerings(
    *,
    provider_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    metadata_mode: ModelMetadataSyncMode,
    sync_mode: str,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> SyncModelOfferingsResponse:
    if sync_mode == "disabled":
        raise ProviderUpstreamError(
            status_code=409,
            body={"error": "model sync is disabled"},
            failure_reason="provider_error",
        )
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

        adapter = default_integration_adapter_registry.get(provider.supported_integration)
        model_names = await adapter.list_models(
            provider=AdapterProvider(
                base_url=provider.base_url,
                api_key=await (secret_registry or get_default_secret_backend_registry()).resolve(
                    credential=active_credential
                ),
            ),
            http_client=http_client,
        )
        synced_names = set(model_names)
        summary = ModelSyncSummary()
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
                    if existing_model.is_active:
                        existing_model.is_active = False
                        summary.disabled += 1
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
                    input_price_per_million_tokens=None,
                    output_price_per_million_tokens=None,
                    cached_input_price_per_million_tokens=None,
                    catalog_input_price_per_million_tokens=(
                        metadata.pricing.input_price_per_million_tokens if metadata else None
                    ),
                    catalog_output_price_per_million_tokens=(
                        metadata.pricing.output_price_per_million_tokens if metadata else None
                    ),
                    catalog_cached_input_price_per_million_tokens=(
                        metadata.pricing.cached_input_price_per_million_tokens if metadata else None
                    ),
                    pricing_catalog_version=metadata.pricing.catalog_version if metadata else None,
                    pricing_last_refreshed_at=synced_at if metadata else None,
                    rate_limit_hints=metadata.rate_limit_hints if metadata else {},
                    metadata_source="catalog" if metadata else "provider",
                    db=db,
                )
                model_offering.metadata_last_synced_at = synced_at
                summary.added += 1
            else:
                was_active = model_offering.is_active
                before = _model_sync_snapshot(model_offering)
                model_offering.is_active = True
                model_offering.metadata_last_synced_at = synced_at
                if metadata is not None:
                    if metadata_mode == ModelMetadataSyncMode.overwrite_catalog:
                        _overwrite_model_offering_from_metadata(
                            model_offering=model_offering,
                            metadata=metadata,
                            refreshed_at=synced_at,
                        )
                    else:
                        _enrich_model_offering_from_metadata(
                            model_offering=model_offering,
                            metadata=metadata,
                            refreshed_at=synced_at,
                        )
                await db.flush()
                if not was_active:
                    summary.reactivated += 1
                elif _model_sync_snapshot(model_offering) != before:
                    summary.updated += 1
                else:
                    summary.unchanged += 1
            synced_models.append(model_offering)
        await activity_facade.record_admin_event(
            actor=actor,
            category="provider",
            action="model_offerings.synced",
            message=f"Synced {len(synced_models)} model offerings.",
            provider_id=provider_id,
            metadata={"model_count": len(synced_models), **summary.model_dump()},
            db=db,
        )

    logger.info(
        "model_offerings_synced",
        provider_id=str(provider_id),
        model_count=len(synced_models),
        org_id=str(scope.org_id),
    )
    return SyncModelOfferingsResponse(
        synced_at=synced_at,
        status="success",
        summary=summary,
        models=[_model_offering_response(model_offering) for model_offering in synced_models],
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
        items=[_model_offering_response(model_offering) for model_offering in model_offerings],
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
    return _model_offering_response(model_offering)


async def test_model_offering(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    payload: TestModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
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

        if provider.supported_integration not in {
            *OPENAI_COMPAT_INTEGRATIONS,
            "anthropic_messages",
        }:
            return TestModelOfferingResponse(
                id=model_offering.id,
                health_status="unsupported",
                last_validation_error=(
                    f"Model testing is not supported for integration "
                    f"'{provider.supported_integration}'."
                ),
            )
        routed_credentials = await _resolve_provider_credential_route(
            provider=provider,
            pool_id=payload.credential_pool_id,
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
                adapter_provider = AdapterProvider(
                    base_url=provider.base_url,
                    api_key=await _api_key_for_routed_credential(
                        provider=provider,
                        credential=credential,
                        secret_registry=secret_registry,
                    ),
                )
                if provider.supported_integration == "anthropic_messages":
                    response = await anthropic_messages_adapter.create_message(
                        provider=adapter_provider,
                        payload=ProviderAnthropicMessagesRequest(
                            model=model_offering.provider_model_name,
                            messages=[{"role": "user", "content": "Reply with ok."}],
                            extra_body={"max_tokens": 8},
                        ),
                        anthropic_version=ANTHROPIC_VERSION,
                        http_client=http_client,
                    )
                else:
                    adapter = default_integration_adapter_registry.get(
                        provider.supported_integration
                    )
                    response = await adapter.create_chat_completion(
                        provider=adapter_provider,
                        payload=ProviderChatCompletionRequest(
                            model=model_offering.provider_model_name,
                            messages=[{"role": "user", "content": "Reply with ok."}],
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
            await _ensure_model_offering_unique(
                org_id=scope.org_id,
                provider_id=provider_id,
                provider_model_name=payload.provider_model_name,
                alias=None,
                current_model_offering_id=model_offering.id,
                db=db,
            )
            model_offering.provider_model_name = payload.provider_model_name
        if "alias" in payload.model_fields_set:
            await _ensure_model_offering_unique(
                org_id=scope.org_id,
                provider_id=provider_id,
                provider_model_name=None,
                alias=payload.alias,
                current_model_offering_id=model_offering.id,
                db=db,
            )
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

    return _model_offering_response(model_offering)


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
            slug = _slugify(payload.slug)
            existing = await repository.get_provider_by_slug(
                slug=slug,
                org_id=scope.org_id,
                db=db,
            )
            if existing is not None and existing.id != provider.id:
                raise ProviderSlugConflictError
            provider.slug = slug
        if payload.base_url is not None:
            provider.base_url = str(payload.base_url).rstrip("/")
        if "description" in payload.model_fields_set:
            provider.description = payload.description
        if payload.capabilities is not None:
            provider.capabilities = payload.capabilities.model_dump()
        if "request_timeout_seconds" in payload.model_fields_set:
            provider.request_timeout_seconds = payload.request_timeout_seconds
        if "max_body_bytes" in payload.model_fields_set:
            provider.max_body_bytes = payload.max_body_bytes
        if "retry_policy" in payload.model_fields_set:
            provider.retry_policy = (
                payload.retry_policy.model_dump() if payload.retry_policy else None
            )
        if "model_sync_mode" in payload.model_fields_set:
            provider.model_sync_mode = payload.model_sync_mode
        if payload.circuit_breaker_policy is not None:
            provider.circuit_breaker_policy = payload.circuit_breaker_policy.model_dump()
        if "max_concurrent_requests" in payload.model_fields_set:
            provider.max_concurrent_requests = payload.max_concurrent_requests
        if payload.is_favorite is not None:
            provider.is_favorite = payload.is_favorite
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
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderChatCompletionResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    request_timeout_seconds = (
        provider.request_timeout_seconds or org_settings.default_request_timeout_seconds
    )
    retry_policy = _retry_policy(
        provider,
        default_retry_count=org_settings.default_retry_count,
    )

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
                        api_key=await _api_key_for_routed_credential(
                            provider=provider,
                            credential=routed_credential,
                            secret_registry=secret_registry,
                        ),
                    ),
                    payload=payload,
                    http_client=http_client,
                )

            try:
                response = await _call_with_retries(
                    call=call_upstream,
                    request_timeout_seconds=request_timeout_seconds,
                    retry_policy=retry_policy,
                )
                _record_circuit_success(provider)
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                    response.provider_credential_id = credential.id
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

    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


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
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError
    if provider.supported_integration != "anthropic_messages":
        raise ProviderAdapterNotFoundError

    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    request_timeout_seconds = (
        provider.request_timeout_seconds or org_settings.default_request_timeout_seconds
    )
    retry_policy = _retry_policy(provider, default_retry_count=org_settings.default_retry_count)
    _raise_if_circuit_open(provider)
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
            ) -> ProviderAnthropicMessagesResponse:
                return await anthropic_messages_adapter.create_message(
                    provider=AdapterProvider(
                        base_url=provider.base_url,
                        api_key=await _api_key_for_routed_credential(
                            provider=provider,
                            credential=routed_credential,
                            secret_registry=secret_registry,
                        ),
                    ),
                    payload=payload,
                    anthropic_version=anthropic_version,
                    http_client=http_client,
                )

            try:
                response = await _call_with_retries(
                    call=call_upstream,
                    request_timeout_seconds=request_timeout_seconds,
                    retry_policy=retry_policy,
                )
                _record_circuit_success(provider)
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                    response.provider_credential_id = credential.id
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

    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


async def _call_with_retries(
    *,
    call: Callable[[], Awaitable[Any]],
    request_timeout_seconds: int,
    retry_policy: dict,
) -> Any:
    max_attempts = retry_policy["max_attempts"] if retry_policy["enabled"] else 1
    last_error: ProviderUpstreamError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with asyncio.timeout(request_timeout_seconds):
                return await call()
        except TimeoutError as exc:
            # A client-side timeout leaves the upstream state unknown. Both callers are
            # non-idempotent completion POSTs, so replaying could double-execute (and
            # double-bill); a timeout is never retried regardless of retry_on_status.
            raise ProviderUpstreamError(
                status_code=504,
                body={"error": "provider request timed out"},
                failure_reason="timeout",
            ) from exc
        except httpx.RequestError as exc:
            last_error = ProviderUpstreamError(
                status_code=502,
                body={"error": "provider upstream connection failed"},
                failure_reason="connection_failed",
            )
            if attempt >= max_attempts or 502 not in retry_policy["retry_on_status"]:
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


def _retry_policy(provider: Provider, *, default_retry_count: int = 0) -> dict:
    stored = provider.retry_policy if isinstance(provider.retry_policy, dict) else {}
    inherited_enabled = default_retry_count > 0
    inherited_attempts = max(1, min(default_retry_count + 1, 10))
    return {
        "enabled": bool(stored.get("enabled", inherited_enabled)),
        "max_attempts": _int_policy_value(
            stored.get("max_attempts"),
            inherited_attempts,
            minimum=1,
            maximum=10,
        ),
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
        raise ProviderUpstreamError(
            status_code=503,
            body={"error": "provider circuit is open"},
            failure_reason="circuit_open",
        )
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
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderChatCompletionStream:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    request_timeout_seconds = (
        provider.request_timeout_seconds or org_settings.default_request_timeout_seconds
    )

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
    concurrency_slot = _provider_concurrency_slot(provider)
    await concurrency_slot.__aenter__()
    stream_returned = False
    try:
        for credential in routed_credentials:
            try:
                async with asyncio.timeout(request_timeout_seconds):
                    stream = await adapter.stream_chat_completion(
                        provider=AdapterProvider(
                            base_url=provider.base_url,
                            api_key=await _api_key_for_routed_credential(
                                provider=provider,
                                credential=credential,
                                secret_registry=secret_registry,
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
                    stream.provider_credential_id = credential.id
                original_chunks = stream.chunks
                original_close = stream.close
                released = False

                async def release_stream(
                    close_stream: Callable[[], Awaitable[None]] = original_close,
                ) -> None:
                    nonlocal released
                    if released:
                        return
                    released = True
                    await close_stream()
                    await concurrency_slot.__aexit__(None, None, None)

                async def managed_chunks(
                    chunks: AsyncIterator[bytes] = original_chunks,
                    routed_credential=credential,
                ) -> AsyncIterator[bytes]:
                    try:
                        async for chunk in chunks:
                            yield chunk
                    except Exception as exc:
                        error = (
                            exc
                            if isinstance(exc, ProviderUpstreamError)
                            else ProviderUpstreamError(
                                status_code=502,
                                body={"error": "provider stream failed"},
                                failure_reason="stream_failed",
                            )
                        )
                        _record_circuit_failure(provider)
                        if routed_credential is not None:
                            await _mark_provider_credential_failed(
                                provider_credential=routed_credential,
                                error=error,
                                db=db,
                            )
                        raise
                    else:
                        _record_circuit_success(provider)
                    finally:
                        await release_stream()

                stream.chunks = managed_chunks()
                stream.close = release_stream
                stream_returned = True
                return stream
            except TimeoutError as exc:
                last_error = ProviderUpstreamError(
                    status_code=504,
                    body={"error": "provider request timed out"},
                    failure_reason="timeout",
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
            except httpx.RequestError as exc:
                last_error = ProviderUpstreamError(
                    status_code=502,
                    body={"error": "provider upstream connection failed"},
                    failure_reason="connection_failed",
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
    finally:
        if not stream_returned:
            await concurrency_slot.__aexit__(None, None, None)


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
    response.integration_capabilities = _provider_integration_capabilities(provider)
    response.readiness = _provider_readiness(provider, response.credential_summary)
    response.operational_state = _provider_operational_state(provider)
    return response


def _provider_integration_capabilities(provider: Provider) -> dict[str, bool]:
    openai_compatible = provider.supported_integration in {
        "openai_compatible",
        "openai_compatible_default",
    }
    anthropic_messages = provider.supported_integration == "anthropic_messages"
    return {
        "openai_compatible_chat": openai_compatible,
        "openai_compatible_models_list": openai_compatible,
        "openai_compatible_responses": openai_compatible,
        "openai_compatible_completions": openai_compatible,
        "streaming": openai_compatible,
        "embeddings": False,
        "native_anthropic_messages": anthropic_messages,
        "native_anthropic_models_list": anthropic_messages,
    }


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
    return (
        "default"
        if provider.supported_integration in {"openai_compatible_default", "anthropic_messages"}
        else "custom"
    )


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
    status, message = _provider_readiness_status(
        provider=provider,
        credential_summary=credential_summary,
        active_pool_count=active_pool_count,
        active_pool_credential_count=active_pool_credential_count,
        active_model_count=active_model_count,
    )
    return ProviderReadiness(
        status=status,
        message=message,
        has_active_provider=provider.is_active,
        has_active_credential=credential_summary.active > 0,
        has_active_pool=active_pool_count > 0,
        has_active_pool_credential=active_pool_credential_count > 0,
        has_active_model=active_model_count > 0,
        active_model_count=active_model_count,
        is_ready=status == "ready",
    )


def _provider_readiness_status(
    *,
    provider: Provider,
    credential_summary: ProviderCredentialSummary,
    active_pool_count: int,
    active_pool_credential_count: int,
    active_model_count: int,
) -> tuple[str, str]:
    if not provider.is_active:
        return "disabled", "Provider is disabled."
    if credential_summary.active == 0:
        return "needs_credential", "Add an active credential."
    active_health = getattr(provider, "_active_credential_health", [])
    if active_health and not any(status == "valid" for status in active_health):
        return "degraded", "Validate an active credential before routing traffic."
    if any(status in {"invalid", "degraded"} for status in active_health):
        return "degraded", "One or more active credentials need attention."
    if active_pool_count == 0 or active_pool_credential_count == 0:
        return "needs_pool", "Create an active pool and attach a credential."
    if active_model_count == 0:
        return "needs_model_sync", "Sync or add at least one active model."
    return "ready", "Provider is ready to serve requests."


def _attach_active_credential_health(
    *,
    providers: list[Provider],
    credentials: list[ProviderCredential],
) -> None:
    grouped: dict[UUID, list[str]] = defaultdict(list)
    for credential in credentials:
        if credential.is_active:
            grouped[credential.provider_id].append(credential.health_status or "unchecked")
    for provider in providers:
        provider._active_credential_health = grouped.get(provider.id, [])


def _provider_operational_state(provider: Provider) -> ProviderOperationalState:
    circuit_policy = _circuit_breaker_policy(provider)
    events = list(_provider_circuit_events.get(provider.id, []))
    open_until = _provider_circuit_open_until.get(provider.id)
    if open_until is not None and open_until <= datetime.now(UTC):
        open_until = None
    return ProviderOperationalState(
        circuit_breaker_enabled=circuit_policy["enabled"],
        circuit_state="open" if open_until is not None else "closed",
        circuit_open_until=open_until,
        recent_circuit_failures=sum(1 for _created_at, succeeded in events if not succeeded),
        recent_circuit_successes=sum(1 for _created_at, succeeded in events if succeeded),
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
            routing_policy = _credential_routing_policy(pool.selection_policy)
            active_pool_credentials = [
                (membership, credential)
                for membership, credential in pool_credentials
                if membership.is_active and credential.is_active
            ]
            if active_pool_credentials:
                routed = _route_pool_credentials(
                    active_pool_credentials,
                    routing_policy=routing_policy,
                )
                if routed and routing_policy in {
                    ProviderCredentialRoutingPolicy.round_robin,
                    ProviderCredentialRoutingPolicy.least_recently_used,
                }:
                    # Stamp selection time so rapid/concurrent requests rotate across the
                    # pool instead of all landing on the same least-recently-used
                    # credential (the timestamp previously only advanced on success).
                    routed[0].last_used_at = repository.datetime_now()
                    await db.flush()
                return routed
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
    return [credential for _, credential in ordered]


def _credential_routing_policy(value: str) -> ProviderCredentialRoutingPolicy:
    try:
        return ProviderCredentialRoutingPolicy(value)
    except ValueError:
        return ProviderCredentialRoutingPolicy.priority


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


async def _api_key_for_routed_credential(
    *,
    provider: Provider,
    credential: ProviderCredential | None,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> str:
    from app.core.security import SecurityError

    try:
        if credential is None:
            return await resolve_legacy_provider_secret(provider=provider)
        return await (secret_registry or get_default_secret_backend_registry()).resolve(
            credential=credential
        )
    except SecurityError as exc:
        # An unreadable ciphertext (rotated/restored encryption key, corruption) becomes
        # a credential failure rather than an uncaught 500: this keeps the multi-credential
        # fallback loop alive and lets credential health reflect the problem.
        raise ProviderUpstreamError(
            status_code=502,
            body={
                "error": {
                    "message": "provider credential could not be decrypted",
                    "type": "credential_error",
                }
            },
            failure_reason="credential_error",
        ) from exc


async def _mark_provider_credential_failed(
    *,
    provider_credential: ProviderCredential,
    error: ProviderUpstreamError,
    db: AsyncSession,
) -> None:
    failed_at = repository.datetime_now()
    failure_reason, failure_message = _credential_failure_details(error)
    provider_credential.health_status = "invalid" if error.status_code in {401, 403} else "degraded"
    provider_credential.last_validation_error = failure_message
    provider_credential.last_failure_at = failed_at
    provider_credential.failure_reason = failure_reason
    provider_credential.failure_message = failure_message
    await db.flush()


def _credential_failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, ProviderUpstreamError):
        if error.failure_reason in {
            "connection_failed",
            "credential_error",
            "rate_limited",
            "timeout",
        }:
            reason = error.failure_reason
        elif error.status_code in {401, 403}:
            reason = "authentication_failed"
        elif error.failure_reason == "provider_5xx":
            reason = "upstream_unavailable"
        else:
            reason = "upstream_error"
        return reason, _upstream_error_message(error)
    if isinstance(error, TimeoutError):
        return "timeout", "Provider validation timed out."
    if isinstance(error, httpx.HTTPError):
        return "connection_failed", "Could not connect to the provider."
    return "validation_failed", str(error) or "Provider credential validation failed."


def _upstream_error_message(error: ProviderUpstreamError) -> str:
    body = error.body
    if isinstance(body, dict):
        detail = body.get("error")
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            return detail["message"]
        if isinstance(detail, str):
            return detail
    return f"Provider returned HTTP {error.status_code}."


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
    refreshed_at: datetime,
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
    _refresh_model_offering_catalog_pricing(
        model_offering=model_offering,
        metadata=metadata,
        refreshed_at=refreshed_at,
    )
    model_offering.rate_limit_hints = {
        **metadata.rate_limit_hints,
        **(model_offering.rate_limit_hints or {}),
    }


def _overwrite_model_offering_from_metadata(
    *,
    model_offering: ModelOffering,
    metadata: ModelMetadata,
    refreshed_at: datetime,
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
    model_offering.input_price_per_million_tokens = None
    model_offering.output_price_per_million_tokens = None
    model_offering.cached_input_price_per_million_tokens = None
    _refresh_model_offering_catalog_pricing(
        model_offering=model_offering,
        metadata=metadata,
        refreshed_at=refreshed_at,
    )
    model_offering.rate_limit_hints = metadata.rate_limit_hints
    model_offering.metadata_source = "catalog"


def _refresh_model_offering_catalog_pricing(
    *,
    model_offering: ModelOffering,
    metadata: ModelMetadata,
    refreshed_at: datetime,
) -> None:
    model_offering.catalog_input_price_per_million_tokens = (
        metadata.pricing.input_price_per_million_tokens
    )
    model_offering.catalog_output_price_per_million_tokens = (
        metadata.pricing.output_price_per_million_tokens
    )
    model_offering.catalog_cached_input_price_per_million_tokens = (
        metadata.pricing.cached_input_price_per_million_tokens
    )
    model_offering.pricing_catalog_version = metadata.pricing.catalog_version
    model_offering.pricing_last_refreshed_at = refreshed_at


def _model_offering_response(model_offering: ModelOffering) -> ModelOfferingResponse:
    effective_input = (
        model_offering.input_price_per_million_tokens
        if model_offering.input_price_per_million_tokens is not None
        else model_offering.catalog_input_price_per_million_tokens
    )
    effective_output = (
        model_offering.output_price_per_million_tokens
        if model_offering.output_price_per_million_tokens is not None
        else model_offering.catalog_output_price_per_million_tokens
    )
    effective_cached_input = (
        model_offering.cached_input_price_per_million_tokens
        if model_offering.cached_input_price_per_million_tokens is not None
        else model_offering.catalog_cached_input_price_per_million_tokens
    )
    has_manual_price = any(
        value is not None
        for value in (
            model_offering.input_price_per_million_tokens,
            model_offering.output_price_per_million_tokens,
            model_offering.cached_input_price_per_million_tokens,
        )
    )
    has_catalog_price = any(
        value is not None
        for value in (
            model_offering.catalog_input_price_per_million_tokens,
            model_offering.catalog_output_price_per_million_tokens,
            model_offering.catalog_cached_input_price_per_million_tokens,
        )
    )
    pricing_source = "unset"
    if has_manual_price:
        pricing_source = "manual"
    elif has_catalog_price:
        pricing_source = "catalog"
    return ModelOfferingResponse(
        id=model_offering.id,
        org_id=model_offering.org_id,
        provider_id=model_offering.provider_id,
        provider_model_name=model_offering.provider_model_name,
        alias=model_offering.alias,
        version=model_offering.version,
        modality=model_offering.modality,
        input_modalities=model_offering.input_modalities,
        output_modalities=model_offering.output_modalities,
        capabilities=model_offering.capabilities,
        context_window=model_offering.context_window,
        input_price_per_million_tokens=model_offering.input_price_per_million_tokens,
        output_price_per_million_tokens=model_offering.output_price_per_million_tokens,
        cached_input_price_per_million_tokens=model_offering.cached_input_price_per_million_tokens,
        catalog_input_price_per_million_tokens=(
            model_offering.catalog_input_price_per_million_tokens
        ),
        catalog_output_price_per_million_tokens=(
            model_offering.catalog_output_price_per_million_tokens
        ),
        catalog_cached_input_price_per_million_tokens=(
            model_offering.catalog_cached_input_price_per_million_tokens
        ),
        effective_input_price_per_million_tokens=effective_input,
        effective_output_price_per_million_tokens=effective_output,
        effective_cached_input_price_per_million_tokens=effective_cached_input,
        pricing_source=pricing_source,
        pricing_catalog_version=model_offering.pricing_catalog_version,
        pricing_last_refreshed_at=model_offering.pricing_last_refreshed_at,
        rate_limit_hints=model_offering.rate_limit_hints,
        metadata_source=model_offering.metadata_source,
        metadata_last_synced_at=model_offering.metadata_last_synced_at,
        is_active=model_offering.is_active,
        created_at=model_offering.created_at,
        updated_at=model_offering.updated_at,
    )


def _combined_modality(input_modalities: list[str], output_modalities: list[str]) -> str:
    ordered = []
    for modality in [*input_modalities, *output_modalities]:
        normalized = modality.strip().lower()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return "+".join(ordered) or "text"


def _model_sync_snapshot(model: ModelOffering) -> tuple:
    return (
        model.version,
        model.modality,
        tuple(model.input_modalities),
        tuple(model.output_modalities),
        tuple(sorted((model.capabilities or {}).items())),
        model.context_window,
        model.metadata_source,
    )
