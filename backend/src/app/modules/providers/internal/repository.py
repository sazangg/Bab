from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.internal.models import Provider, ProviderKey, ProviderModel


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


async def create_provider_key(
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
) -> ProviderKey:
    provider_key = ProviderKey(
        org_id=org_id,
        provider_id=provider_id,
        created_by=created_by,
        name=name,
        key_prefix=key_prefix,
        api_key_encrypted=api_key_encrypted,
        routing_policy=routing_policy,
        priority=priority,
    )
    db.add(provider_key)
    await db.flush()
    return provider_key


async def list_provider_keys(
    *,
    org_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> list[ProviderKey]:
    result = await db.scalars(
        select(ProviderKey)
        .where(ProviderKey.org_id == org_id, ProviderKey.provider_id == provider_id)
        .order_by(
            ProviderKey.is_active.desc(),
            ProviderKey.priority.asc(),
            ProviderKey.created_at.asc(),
        )
    )
    return list(result)


async def get_provider_key(
    *,
    org_id: UUID,
    provider_key_id: UUID,
    db: AsyncSession,
) -> ProviderKey | None:
    return await db.scalar(
        select(ProviderKey).where(
            ProviderKey.org_id == org_id,
            ProviderKey.id == provider_key_id,
        )
    )


async def mark_provider_key_used(*, provider_key: ProviderKey, db: AsyncSession) -> None:
    provider_key.last_used_at = datetime_now()
    provider_key.last_successful_request_at = datetime_now()
    provider_key.health_status = "valid"
    provider_key.last_validation_error = None
    await db.flush()


async def create_provider_model(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model_name: str,
    alias: str | None,
    version: str | None = None,
    modality: str = "text",
    capabilities: dict | None = None,
    context_window: int | None = None,
    input_price_per_million_tokens: int | None = None,
    output_price_per_million_tokens: int | None = None,
    cached_input_price_per_million_tokens: int | None = None,
    rate_limit_hints: dict | None = None,
    db: AsyncSession,
) -> ProviderModel:
    provider_model = ProviderModel(
        org_id=org_id,
        provider_id=provider_id,
        provider_model_name=provider_model_name,
        alias=alias,
        version=version,
        modality=modality,
        capabilities=capabilities or {},
        context_window=context_window,
        input_price_per_million_tokens=input_price_per_million_tokens,
        output_price_per_million_tokens=output_price_per_million_tokens,
        cached_input_price_per_million_tokens=cached_input_price_per_million_tokens,
        rate_limit_hints=rate_limit_hints or {},
    )
    db.add(provider_model)
    await db.flush()
    return provider_model


async def get_provider_model_by_name(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model_name: str,
    db: AsyncSession,
) -> ProviderModel | None:
    return await db.scalar(
        select(ProviderModel).where(
            ProviderModel.org_id == org_id,
            ProviderModel.provider_id == provider_id,
            ProviderModel.provider_model_name == provider_model_name,
        )
    )


async def get_provider_model(
    *,
    org_id: UUID,
    provider_model_id: UUID,
    db: AsyncSession,
) -> ProviderModel | None:
    return await db.scalar(
        select(ProviderModel).where(
            ProviderModel.org_id == org_id,
            ProviderModel.id == provider_model_id,
        )
    )


async def list_provider_models(
    *,
    org_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> list[ProviderModel]:
    result = await db.scalars(
        select(ProviderModel)
        .where(ProviderModel.org_id == org_id, ProviderModel.provider_id == provider_id)
        .order_by(ProviderModel.is_active.desc(), ProviderModel.provider_model_name.asc())
    )
    return list(result)


def datetime_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
