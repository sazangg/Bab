from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.internal.models import Provider, ProviderKey, ProviderModel


async def create_provider(
    *,
    org_id: UUID,
    name: str,
    base_url: str,
    api_key_encrypted: str,
    adapter_type: str,
    db: AsyncSession,
) -> Provider:
    provider = Provider(
        org_id=org_id,
        name=name,
        base_url=base_url,
        api_key_encrypted=api_key_encrypted,
        adapter_type=adapter_type,
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
    name: str,
    key_prefix: str,
    api_key_encrypted: str,
    priority: int,
    db: AsyncSession,
) -> ProviderKey:
    provider_key = ProviderKey(
        org_id=org_id,
        provider_id=provider_id,
        name=name,
        key_prefix=key_prefix,
        api_key_encrypted=api_key_encrypted,
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
        .order_by(ProviderKey.priority.asc(), ProviderKey.created_at.asc())
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


async def create_provider_model(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model_name: str,
    alias: str | None,
    db: AsyncSession,
) -> ProviderModel:
    provider_model = ProviderModel(
        org_id=org_id,
        provider_id=provider_id,
        provider_model_name=provider_model_name,
        alias=alias,
    )
    db.add(provider_model)
    await db.flush()
    return provider_model


async def list_provider_models(
    *,
    org_id: UUID,
    provider_id: UUID,
    db: AsyncSession,
) -> list[ProviderModel]:
    result = await db.scalars(
        select(ProviderModel)
        .where(ProviderModel.org_id == org_id, ProviderModel.provider_id == provider_id)
        .order_by(ProviderModel.provider_model_name.asc())
    )
    return list(result)
