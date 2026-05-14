from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.internal.models import ModelOffering, Provider, ProviderCredential


async def create_provider(
    *,
    org_id: UUID,
    name: str,
    slug: str,
    base_url: str,
    api_key_encrypted: str | None,
    adapter_type: str,
    description: str | None,
    capabilities: dict,
    request_timeout_seconds: int,
    max_body_bytes: int | None,
    retry_policy: dict,
    fallback_policy: dict,
    circuit_breaker_policy: dict,
    max_concurrent_requests: int | None,
    db: AsyncSession,
) -> Provider:
    provider = Provider(
        org_id=org_id,
        name=name,
        slug=slug,
        base_url=base_url,
        api_key_encrypted=api_key_encrypted,
        adapter_type=adapter_type,
        display_name=name,
        description=description,
        capabilities=capabilities,
        request_timeout_seconds=request_timeout_seconds,
        max_body_bytes=max_body_bytes,
        retry_policy=retry_policy,
        fallback_policy=fallback_policy,
        circuit_breaker_policy=circuit_breaker_policy,
        max_concurrent_requests=max_concurrent_requests,
    )
    db.add(provider)
    await db.flush()
    return provider


async def list_providers(*, org_id: UUID, db: AsyncSession) -> list[Provider]:
    result = await db.scalars(
        select(Provider).where(Provider.org_id == org_id).order_by(Provider.created_at.desc())
    )
    return list(result)


async def get_provider(*, provider_id: UUID, org_id: UUID, db: AsyncSession) -> Provider | None:
    return await db.scalar(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )


async def create_provider_credential(
    *,
    org_id: UUID,
    provider_id: UUID,
    created_by: UUID,
    name: str,
    key_prefix: str,
    api_key_encrypted: str,
    routing_policy: str,
    priority: int,
    db: AsyncSession,
) -> ProviderCredential:
    provider_credential = ProviderCredential(
        org_id=org_id,
        provider_id=provider_id,
        created_by=created_by,
        name=name,
        key_prefix=key_prefix,
        api_key_encrypted=api_key_encrypted,
        routing_policy=routing_policy,
        priority=priority,
    )
    db.add(provider_credential)
    await db.flush()
    return provider_credential


async def list_provider_credentials(
    *,
    org_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> list[ProviderCredential]:
    result = await db.scalars(
        select(ProviderCredential)
        .where(ProviderCredential.org_id == org_id, ProviderCredential.provider_id == provider_id)
        .order_by(
            ProviderCredential.is_active.desc(),
            ProviderCredential.priority.asc(),
            ProviderCredential.created_at.asc(),
        )
    )
    return list(result)


async def get_provider_credential(
    *,
    org_id: UUID,
    provider_credential_id: UUID,
    db: AsyncSession,
) -> ProviderCredential | None:
    return await db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.org_id == org_id,
            ProviderCredential.id == provider_credential_id,
        )
    )


async def mark_provider_credential_used(
    *,
    provider_credential: ProviderCredential,
    db: AsyncSession,
) -> None:
    provider_credential.last_used_at = datetime_now()
    provider_credential.last_successful_request_at = datetime_now()
    provider_credential.health_status = "valid"
    provider_credential.last_validation_error = None
    await db.flush()


async def create_model_offering(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model_name: str,
    alias: str | None,
    version: str | None = None,
    modality: str = "text",
    input_modalities: list[str] | None = None,
    output_modalities: list[str] | None = None,
    capabilities: dict | None = None,
    context_window: int | None = None,
    input_price_per_million_tokens: int | None = None,
    output_price_per_million_tokens: int | None = None,
    cached_input_price_per_million_tokens: int | None = None,
    rate_limit_hints: dict | None = None,
    db: AsyncSession,
) -> ModelOffering:
    model_offering = ModelOffering(
        org_id=org_id,
        provider_id=provider_id,
        provider_model_name=provider_model_name,
        alias=alias,
        version=version,
        modality=modality,
        input_modalities=input_modalities or ["text"],
        output_modalities=output_modalities or ["text"],
        capabilities=capabilities or {},
        context_window=context_window,
        input_price_per_million_tokens=input_price_per_million_tokens,
        output_price_per_million_tokens=output_price_per_million_tokens,
        cached_input_price_per_million_tokens=cached_input_price_per_million_tokens,
        rate_limit_hints=rate_limit_hints or {},
    )
    db.add(model_offering)
    await db.flush()
    return model_offering


async def get_model_offering_by_name(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model_name: str,
    db: AsyncSession,
) -> ModelOffering | None:
    return await db.scalar(
        select(ModelOffering).where(
            ModelOffering.org_id == org_id,
            ModelOffering.provider_id == provider_id,
            ModelOffering.provider_model_name == provider_model_name,
        )
    )


async def get_model_offering(
    *,
    org_id: UUID,
    model_offering_id: UUID,
    db: AsyncSession,
) -> ModelOffering | None:
    return await db.scalar(
        select(ModelOffering).where(
            ModelOffering.org_id == org_id,
            ModelOffering.id == model_offering_id,
        )
    )


async def list_model_offerings(
    *,
    org_id: UUID,
    provider_id: UUID,
    search: str | None,
    modalities: list[str] | None,
    is_active: bool | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> tuple[list[ModelOffering], int]:
    filters = [
        ModelOffering.org_id == org_id,
        ModelOffering.provider_id == provider_id,
    ]
    if search:
        normalized_search = f"%{search.strip().lower()}%"
        filters.append(
            or_(
                func.lower(ModelOffering.provider_model_name).like(normalized_search),
                func.lower(ModelOffering.alias).like(normalized_search),
            )
        )
    if modalities:
        for modality in modalities:
            normalized_modality = modality.strip().lower()
            if not normalized_modality:
                continue
            filters.append(
                or_(
                    func.lower(ModelOffering.modality) == normalized_modality,
                    func.lower(ModelOffering.modality).like(f"{normalized_modality}+%"),
                    func.lower(ModelOffering.modality).like(f"%+{normalized_modality}+%"),
                    func.lower(ModelOffering.modality).like(f"%+{normalized_modality}"),
                )
            )
    if is_active is not None:
        filters.append(ModelOffering.is_active == is_active)

    total = await db.scalar(select(func.count()).select_from(ModelOffering).where(*filters))
    result = await db.scalars(
        select(ModelOffering)
        .where(*filters)
        .order_by(ModelOffering.is_active.desc(), ModelOffering.provider_model_name.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result), int(total or 0)


def datetime_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)

