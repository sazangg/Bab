import re
from collections import defaultdict
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.activity import facade as activity_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers.errors import (
    ProviderNotFoundError,
    ProviderSlugConflictError,
)
from app.modules.providers.internal import execution, repository
from app.modules.providers.internal.adapters import (
    OPENAI_COMPAT_ADAPTER,
)
from app.modules.providers.internal.models import (
    Provider,
    ProviderCredential,
)
from app.modules.providers.read_models import (
    provider_integration_capabilities,
)
from app.modules.providers.schemas import (
    CreateProviderRequest,
    ProviderCredentialSummary,
    ProviderReadiness,
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


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider


def _to_response(
    provider: Provider,
    credential_summary: ProviderCredentialSummary | None = None,
) -> ProviderResponse:
    response = ProviderResponse.model_validate(provider)
    response.credential_summary = credential_summary or ProviderCredentialSummary()
    response.catalog_type = _provider_catalog_type(provider)
    response.capabilities = _aggregate_provider_capabilities(provider)
    response.integration_capabilities = provider_integration_capabilities(provider)
    response.readiness = _provider_readiness(provider, response.credential_summary)
    response.operational_state = execution.provider_operational_state(provider)
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






def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "provider"


