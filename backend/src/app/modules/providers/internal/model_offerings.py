from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.errors import (
    ProviderCredentialRequiredError,
    ProviderNotFoundError,
    ProviderResourceConflictError,
    ProviderUpstreamError,
)
from app.modules.providers.internal import credential_routing, repository
from app.modules.providers.internal.adapters import (
    ANTHROPIC_VERSION,
    OPENAI_COMPAT_INTEGRATIONS,
    AdapterProvider,
    anthropic_messages_adapter,
    default_integration_adapter_registry,
)
from app.modules.providers.internal.model_metadata import (
    ModelMetadata,
    default_model_metadata_registry,
)
from app.modules.providers.internal.models import (
    ModelCatalogEntry,
    ModelOffering,
    Provider,
    ProviderModelCatalogMapping,
)
from app.modules.providers.internal.secret_backends import (
    ProviderSecretBackendRegistry,
    get_default_secret_backend_registry,
)
from app.modules.providers.schemas import (
    CreateProviderModelOfferingRequest,
    ModelMetadataSyncMode,
    ModelSyncSummary,
    ProviderAnthropicMessagesRequest,
    ProviderChatCompletionRequest,
    ProviderModelOfferingPageResponse,
    ProviderModelOfferingResponse,
    SyncProviderModelOfferingsResponse,
    TestProviderModelOfferingRequest,
    TestProviderModelOfferingResponse,
    UpdateProviderModelOfferingRequest,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _SyncedModelOffering:
    model_offering: ModelOffering
    metadata: ModelMetadata | None


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider


async def _get_model_offering_or_raise(
    *,
    provider_id: UUID,
    model_offering_id: UUID,
    scope: Scope,
    db: AsyncSession,
) -> ModelOffering:
    model_offering = await repository.get_model_offering(
        org_id=scope.org_id,
        model_offering_id=model_offering_id,
        db=db,
    )
    if model_offering is None or model_offering.provider_id != provider_id:
        raise ProviderNotFoundError
    return model_offering


async def create_model_offering(
    *,
    provider_id: UUID,
    payload: CreateProviderModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderModelOfferingResponse:
    async with transaction(db):
        await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        await _ensure_model_offering_unique(
            org_id=scope.org_id,
            provider_id=provider_id,
            provider_model_name=payload.provider_model_name,
            db=db,
        )
        model_offering = await repository.create_model_offering(
            org_id=scope.org_id,
            provider_id=provider_id,
            provider_model_name=payload.provider_model_name,
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
) -> SyncProviderModelOfferingsResponse:
    if sync_mode == "disabled":
        raise ProviderUpstreamError(
            status_code=409,
            body={"error": "model sync is disabled"},
            failure_reason="provider_error",
        )
    async with transaction(db):
        provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
        active_credential = await _active_sync_credential(
            provider_id=provider_id,
            scope=scope,
            db=db,
        )
        model_names = await _provider_model_names(
            provider=provider,
            active_credential=active_credential,
            http_client=http_client,
            secret_registry=secret_registry,
        )
        await repository.mark_provider_credential_used(
            provider_credential=active_credential,
            db=db,
        )
        synced_names = set(model_names)
        summary = ModelSyncSummary()
        if sync_mode == "replace":
            await _deactivate_missing_models_for_replace_sync(
                org_id=scope.org_id,
                provider_id=provider_id,
                synced_names=synced_names,
                summary=summary,
                db=db,
            )
        synced_models = []
        synced_at = datetime.now(UTC)
        for model_name in sorted(set(model_names)):
            synced_model = await _sync_single_model_offering(
                org_id=scope.org_id,
                provider=provider,
                provider_id=provider_id,
                provider_model_name=model_name,
                metadata_mode=metadata_mode,
                synced_at=synced_at,
                summary=summary,
                db=db,
            )
            if synced_model.metadata is not None:
                await _sync_model_catalog_metadata(
                    org_id=scope.org_id,
                    provider=provider,
                    provider_id=provider_id,
                    model_offering=synced_model.model_offering,
                    metadata=synced_model.metadata,
                    synced_at=synced_at,
                    db=db,
                )
            synced_models.append(synced_model.model_offering)
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
    mapping_by_model = await repository.list_primary_catalog_mappings(
        org_id=scope.org_id,
        model_offering_ids=[model.id for model in synced_models],
        db=db,
    )
    return SyncProviderModelOfferingsResponse(
        synced_at=synced_at,
        status="success",
        summary=summary,
        models=[
            _model_offering_response(
                model_offering,
                catalog_mapping=mapping_by_model.get(model_offering.id),
            )
            for model_offering in synced_models
        ],
    )


async def _active_sync_credential(
    *,
    provider_id: UUID,
    scope: Scope,
    db: AsyncSession,
):
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
    return active_credential


async def _provider_model_names(
    *,
    provider: Provider,
    active_credential,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None,
) -> list[str]:
    adapter = default_integration_adapter_registry.get(provider.supported_integration)
    return await adapter.list_models(
        provider=AdapterProvider(
            base_url=provider.base_url,
            api_key=await (secret_registry or get_default_secret_backend_registry()).resolve(
                credential=active_credential
            ),
        ),
        http_client=http_client,
    )


async def _deactivate_missing_models_for_replace_sync(
    *,
    org_id: UUID,
    provider_id: UUID,
    synced_names: set[str],
    summary: ModelSyncSummary,
    db: AsyncSession,
) -> None:
    existing_models, _ = await repository.list_model_offerings(
        org_id=org_id,
        provider_id=provider_id,
        search=None,
        modalities=None,
        is_active=None,
        limit=10_000,
        offset=0,
        db=db,
    )
    for existing_model in existing_models:
        if existing_model.provider_model_name not in synced_names and existing_model.is_active:
            existing_model.is_active = False
            summary.disabled += 1


async def _sync_single_model_offering(
    *,
    org_id: UUID,
    provider: Provider,
    provider_id: UUID,
    provider_model_name: str,
    metadata_mode: ModelMetadataSyncMode,
    synced_at: datetime,
    summary: ModelSyncSummary,
    db: AsyncSession,
) -> _SyncedModelOffering:
    metadata = default_model_metadata_registry.get(
        provider=provider,
        provider_model_name=provider_model_name,
    )
    model_offering = await repository.get_model_offering_by_name(
        org_id=org_id,
        provider_id=provider_id,
        provider_model_name=provider_model_name,
        db=db,
    )
    if model_offering is None:
        model_offering = await _create_synced_model_offering(
            org_id=org_id,
            provider_id=provider_id,
            provider_model_name=provider_model_name,
            metadata=metadata,
            synced_at=synced_at,
            db=db,
        )
        summary.added += 1
        return _SyncedModelOffering(model_offering=model_offering, metadata=metadata)

    was_active = model_offering.is_active
    before = _model_sync_snapshot(model_offering)
    model_offering.is_active = True
    model_offering.metadata_last_synced_at = synced_at
    if metadata is not None:
        _apply_synced_model_metadata(
            model_offering=model_offering,
            metadata=metadata,
            metadata_mode=metadata_mode,
            synced_at=synced_at,
        )
    await db.flush()
    if not was_active:
        summary.reactivated += 1
    elif _model_sync_snapshot(model_offering) != before:
        summary.updated += 1
    else:
        summary.unchanged += 1
    return _SyncedModelOffering(model_offering=model_offering, metadata=metadata)


async def _create_synced_model_offering(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model_name: str,
    metadata: ModelMetadata | None,
    synced_at: datetime,
    db: AsyncSession,
) -> ModelOffering:
    model_offering = await repository.create_model_offering(
        org_id=org_id,
        provider_id=provider_id,
        provider_model_name=provider_model_name,
        version=metadata.version if metadata else None,
        modality=(
            _combined_modality(metadata.input_modalities, metadata.output_modalities)
            if metadata
            else "text"
        ),
        input_modalities=metadata.input_modalities if metadata else ["text"],
        output_modalities=metadata.output_modalities if metadata else ["text"],
        capabilities=metadata.capabilities if metadata else _default_model_capabilities(),
        context_window=metadata.context_window if metadata else None,
        input_price_per_million_tokens=None,
        output_price_per_million_tokens=None,
        cached_input_price_per_million_tokens=None,
        rate_limit_hints=metadata.rate_limit_hints if metadata else {},
        metadata_source="catalog" if metadata else "provider",
        db=db,
    )
    model_offering.metadata_last_synced_at = synced_at
    return model_offering


def _apply_synced_model_metadata(
    *,
    model_offering: ModelOffering,
    metadata: ModelMetadata,
    metadata_mode: ModelMetadataSyncMode,
    synced_at: datetime,
) -> None:
    if metadata_mode == ModelMetadataSyncMode.overwrite_catalog:
        _overwrite_model_offering_from_metadata(
            model_offering=model_offering,
            metadata=metadata,
            refreshed_at=synced_at,
        )
        return
    _enrich_model_offering_from_metadata(
        model_offering=model_offering,
        metadata=metadata,
        refreshed_at=synced_at,
    )


async def _sync_model_catalog_metadata(
    *,
    org_id: UUID,
    provider: Provider,
    provider_id: UUID,
    model_offering: ModelOffering,
    metadata: ModelMetadata,
    synced_at: datetime,
    db: AsyncSession,
) -> None:
    catalog_entry = await repository.upsert_model_catalog_entry(
        canonical_name=metadata.provider_model_name,
        provider_family=_provider_family(provider),
        version=metadata.version,
        input_modalities=metadata.input_modalities,
        output_modalities=metadata.output_modalities,
        capabilities=metadata.capabilities,
        context_window=metadata.context_window,
        input_price_per_million_tokens=metadata.pricing.input_price_per_million_tokens,
        output_price_per_million_tokens=metadata.pricing.output_price_per_million_tokens,
        cached_input_price_per_million_tokens=(
            metadata.pricing.cached_input_price_per_million_tokens
        ),
        metadata_source="static",
        catalog_version=metadata.pricing.catalog_version
        or metadata.metadata_version
        or "unversioned",
        refreshed_at=synced_at,
        db=db,
    )
    await repository.upsert_provider_model_catalog_mapping(
        org_id=org_id,
        provider_id=provider_id,
        model_offering_id=model_offering.id,
        catalog_entry_id=catalog_entry.id,
        match_source="static_metadata",
        confidence="exact",
        input_price_per_million_tokens=metadata.pricing.input_price_per_million_tokens,
        output_price_per_million_tokens=metadata.pricing.output_price_per_million_tokens,
        cached_input_price_per_million_tokens=(
            metadata.pricing.cached_input_price_per_million_tokens
        ),
        pricing_source="static" if _metadata_has_pricing(metadata) else None,
        refreshed_at=synced_at,
        db=db,
    )


def _metadata_has_pricing(metadata: ModelMetadata) -> bool:
    return any(
        value is not None
        for value in (
            metadata.pricing.input_price_per_million_tokens,
            metadata.pricing.output_price_per_million_tokens,
            metadata.pricing.cached_input_price_per_million_tokens,
        )
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
    mapping_by_model = await repository.list_primary_catalog_mappings(
        org_id=scope.org_id,
        model_offering_ids=[model.id for model in model_offerings],
        db=db,
    )
    return ProviderModelOfferingPageResponse(
        items=[
            _model_offering_response(
                model_offering,
                catalog_mapping=mapping_by_model.get(model_offering.id),
            )
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
) -> ProviderModelOfferingResponse:
    model_offering = await repository.get_model_offering(
        org_id=scope.org_id,
        model_offering_id=model_offering_id,
        db=db,
    )
    if model_offering is None:
        raise ProviderNotFoundError
    mapping_by_model = await repository.list_primary_catalog_mappings(
        org_id=scope.org_id,
        model_offering_ids=[model_offering.id],
        db=db,
    )
    return _model_offering_response(
        model_offering,
        catalog_mapping=mapping_by_model.get(model_offering.id),
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
            return TestProviderModelOfferingResponse(
                id=model_offering.id,
                health_status="unsupported",
                last_validation_error=(
                    f"Model testing is not supported for integration "
                    f"'{provider.supported_integration}'."
                ),
            )
        routed_credentials = await credential_routing.resolve_provider_credential_route(
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
                    api_key=await credential_routing.api_key_for_routed_credential(
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
                    await credential_routing.mark_provider_credential_failed(
                        provider_credential=credential,
                        error=exc,
                        db=db,
                    )
                if (
                    payload.provider_credential_id is not None
                    or not credential_routing.should_try_next_credential(exc)
                ):
                    break
            except Exception as exc:  # noqa: BLE001 - surfaced as model validation result.
                error = str(exc)
                break

        if last_error is not None and error is None:
            error = str(last_error.body)

    return TestProviderModelOfferingResponse(
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
    payload: UpdateProviderModelOfferingRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProviderModelOfferingResponse:
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
                current_model_offering_id=model_offering.id,
                db=db,
            )
            model_offering.provider_model_name = payload.provider_model_name
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

    mapping_by_model = await repository.list_primary_catalog_mappings(
        org_id=scope.org_id,
        model_offering_ids=[model_offering.id],
        db=db,
    )
    return _model_offering_response(
        model_offering,
        catalog_mapping=mapping_by_model.get(model_offering.id),
    )


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


def _provider_family(provider: Provider) -> str:
    slug = (provider.slug or "").strip()
    if slug:
        return slug
    return (provider.supported_integration or "global").strip() or "global"


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
    model_offering.rate_limit_hints = metadata.rate_limit_hints
    model_offering.metadata_source = "catalog"


def _model_offering_response(
    model_offering: ModelOffering,
    *,
    catalog_mapping: tuple[ProviderModelCatalogMapping, ModelCatalogEntry] | None = None,
) -> ProviderModelOfferingResponse:
    mapping, catalog_entry = catalog_mapping if catalog_mapping is not None else (None, None)
    effective_input = _effective_price(
        manual=model_offering.input_price_per_million_tokens,
        mapping=mapping.input_price_per_million_tokens if mapping is not None else None,
        catalog=catalog_entry.input_price_per_million_tokens if catalog_entry is not None else None,
    )
    effective_output = _effective_price(
        manual=model_offering.output_price_per_million_tokens,
        mapping=mapping.output_price_per_million_tokens if mapping is not None else None,
        catalog=catalog_entry.output_price_per_million_tokens
        if catalog_entry is not None
        else None,
    )
    effective_cached_input = _effective_price(
        manual=model_offering.cached_input_price_per_million_tokens,
        mapping=mapping.cached_input_price_per_million_tokens if mapping is not None else None,
        catalog=(
            catalog_entry.cached_input_price_per_million_tokens
            if catalog_entry is not None
            else None
        ),
    )
    has_manual_price = any(
        value is not None
        for value in (
            model_offering.input_price_per_million_tokens,
            model_offering.output_price_per_million_tokens,
            model_offering.cached_input_price_per_million_tokens,
        )
    )
    pricing_source = "unset"
    if has_manual_price:
        pricing_source = "manual"
    elif mapping is not None and any(
        value is not None
        for value in (
            mapping.input_price_per_million_tokens,
            mapping.output_price_per_million_tokens,
            mapping.cached_input_price_per_million_tokens,
        )
    ):
        pricing_source = "catalog_mapping"
    elif catalog_entry is not None and any(
        value is not None
        for value in (
            catalog_entry.input_price_per_million_tokens,
            catalog_entry.output_price_per_million_tokens,
            catalog_entry.cached_input_price_per_million_tokens,
        )
    ):
        pricing_source = "catalog"
    return ProviderModelOfferingResponse(
        id=model_offering.id,
        org_id=model_offering.org_id,
        provider_id=model_offering.provider_id,
        provider_model_name=model_offering.provider_model_name,
        version=model_offering.version,
        modality=model_offering.modality,
        input_modalities=model_offering.input_modalities,
        output_modalities=model_offering.output_modalities,
        capabilities=model_offering.capabilities,
        context_window=model_offering.context_window,
        input_price_per_million_tokens=model_offering.input_price_per_million_tokens,
        output_price_per_million_tokens=model_offering.output_price_per_million_tokens,
        cached_input_price_per_million_tokens=model_offering.cached_input_price_per_million_tokens,
        effective_input_price_per_million_tokens=effective_input,
        effective_output_price_per_million_tokens=effective_output,
        effective_cached_input_price_per_million_tokens=effective_cached_input,
        pricing_source=pricing_source,
        rate_limit_hints=model_offering.rate_limit_hints,
        metadata_source=model_offering.metadata_source,
        metadata_last_synced_at=model_offering.metadata_last_synced_at,
        is_active=model_offering.is_active,
        created_at=model_offering.created_at,
        updated_at=model_offering.updated_at,
    )


def _effective_price(
    *,
    manual: int | None,
    mapping: int | None,
    catalog: int | None,
) -> int | None:
    if manual is not None:
        return manual
    if mapping is not None:
        return mapping
    return catalog


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
