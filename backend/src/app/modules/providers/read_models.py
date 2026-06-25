from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.internal.models import (
    CredentialPool,
    CredentialPoolCredential,
    ModelCatalogEntry,
    ModelOffering,
    Provider,
    ProviderCredential,
    ProviderModelCatalogMapping,
)
from app.modules.providers.schemas import (
    CredentialPoolLabel,
    ProviderCredentialLabel,
    ProviderLabel,
    ProviderRouteAttemptSnapshot,
    ProviderRouteResource,
    ProviderRouteResourceKey,
)


async def get_provider_labels(
    *,
    org_id: UUID,
    provider_ids: set[UUID],
    db: AsyncSession,
) -> dict[UUID, ProviderLabel]:
    if not provider_ids:
        return {}
    rows = await db.scalars(
        select(Provider).where(Provider.org_id == org_id, Provider.id.in_(provider_ids))
    )
    return {
        provider.id: ProviderLabel(id=provider.id, name=provider.name, slug=provider.slug)
        for provider in rows
    }


async def get_credential_pool_labels(
    *,
    org_id: UUID,
    pool_ids: set[UUID],
    db: AsyncSession,
) -> dict[UUID, CredentialPoolLabel]:
    if not pool_ids:
        return {}
    rows = await db.scalars(
        select(CredentialPool).where(
            CredentialPool.org_id == org_id,
            CredentialPool.id.in_(pool_ids),
        )
    )
    return {
        pool.id: CredentialPoolLabel(id=pool.id, name=pool.name)
        for pool in rows
    }


async def get_provider_credential_labels(
    *,
    org_id: UUID,
    credential_ids: set[UUID],
    db: AsyncSession,
) -> dict[UUID, ProviderCredentialLabel]:
    if not credential_ids:
        return {}
    rows = await db.scalars(
        select(ProviderCredential).where(
            ProviderCredential.org_id == org_id,
            ProviderCredential.id.in_(credential_ids),
        )
    )
    return {
        credential.id: ProviderCredentialLabel(
            id=credential.id,
            name=credential.name,
            key_prefix=credential.key_prefix,
        )
        for credential in rows
    }


async def find_provider_credential_ids(
    *,
    org_id: UUID,
    search: str,
    db: AsyncSession,
) -> set[UUID]:
    term = search.strip()
    if not term:
        return set()
    rows = await db.scalars(
        select(ProviderCredential.id).where(
            ProviderCredential.org_id == org_id,
            or_(
                ProviderCredential.name.icontains(term, autoescape=True),
                ProviderCredential.key_prefix.icontains(term, autoescape=True),
            ),
        )
    )
    return set(rows)


async def get_route_attempt_snapshot(
    *,
    org_id: UUID,
    provider_id: UUID,
    credential_pool_id: UUID,
    provider_credential_id: UUID | None,
    model_offering_id: UUID,
    db: AsyncSession,
) -> ProviderRouteAttemptSnapshot:
    provider = await _get_provider(org_id=org_id, provider_id=provider_id, db=db)
    pool = await _get_credential_pool(org_id=org_id, pool_id=credential_pool_id, db=db)
    credential = (
        await _get_provider_credential(
            org_id=org_id,
            credential_id=provider_credential_id,
            db=db,
        )
        if provider_credential_id is not None
        else None
    )
    offering = await _get_model_offering(
        org_id=org_id,
        model_offering_id=model_offering_id,
        db=db,
    )
    return ProviderRouteAttemptSnapshot(
        provider_name=provider.name if provider else None,
        provider_slug=provider.slug if provider else None,
        credential_pool_name=pool.name if pool else None,
        provider_credential_name=credential.name if credential else None,
        provider_credential_prefix=credential.key_prefix if credential else None,
        provider_model_offering_name=offering.provider_model_name if offering else None,
        capability_snapshot={
            "provider_capabilities": provider.capabilities if provider else {},
            "integration": provider.supported_integration if provider else None,
            "model_capabilities": offering.capabilities if offering else {},
            "input_modalities": offering.input_modalities if offering else [],
            "output_modalities": offering.output_modalities if offering else [],
            "context_window": offering.context_window if offering else None,
        },
    )


async def get_route_resource(
    *,
    org_id: UUID,
    provider_id: UUID,
    credential_pool_id: UUID,
    model_offering_id: UUID,
    include_provider: bool = True,
    include_pricing: bool = True,
    db: AsyncSession,
) -> ProviderRouteResource:
    key = ProviderRouteResourceKey(
        provider_id=provider_id,
        credential_pool_id=credential_pool_id,
        model_offering_id=model_offering_id,
    )
    resources = await get_route_resources(
        org_id=org_id,
        resources={key},
        include_provider=include_provider,
        include_pricing=include_pricing,
        db=db,
    )
    return resources[key]


async def get_route_resources(
    *,
    org_id: UUID,
    resources: set[ProviderRouteResourceKey],
    include_provider: bool = True,
    include_pricing: bool = True,
    db: AsyncSession,
) -> dict[ProviderRouteResourceKey, ProviderRouteResource]:
    if not resources:
        return {}

    provider_ids = {resource.provider_id for resource in resources}
    pool_ids = {resource.credential_pool_id for resource in resources}
    model_ids = {resource.model_offering_id for resource in resources}

    providers = (
        {
            provider.id: provider
            for provider in await db.scalars(
                select(Provider).where(Provider.org_id == org_id, Provider.id.in_(provider_ids))
            )
        }
        if include_provider
        else {}
    )
    pools = {
        pool.id: pool
        for pool in await db.scalars(
            select(CredentialPool).where(
                CredentialPool.org_id == org_id,
                CredentialPool.id.in_(pool_ids),
            )
        )
    }
    models = {
        model.id: model
        for model in await db.scalars(
            select(ModelOffering).where(
                ModelOffering.org_id == org_id,
                ModelOffering.id.in_(model_ids),
            )
        )
    }
    catalog_mappings = (
        {
            model_offering_id: (mapping, catalog_entry)
            for model_offering_id, mapping, catalog_entry in await db.execute(
                select(
                    ProviderModelCatalogMapping.provider_model_offering_id,
                    ProviderModelCatalogMapping,
                    ModelCatalogEntry,
                )
                .join(
                    ModelCatalogEntry,
                    ModelCatalogEntry.id == ProviderModelCatalogMapping.catalog_entry_id,
                )
                .where(
                    ProviderModelCatalogMapping.org_id == org_id,
                    ProviderModelCatalogMapping.provider_model_offering_id.in_(model_ids),
                    ProviderModelCatalogMapping.is_active.is_(True),
                    ProviderModelCatalogMapping.is_primary.is_(True),
                )
            )
        }
        if include_pricing
        else {}
    )
    ready_pool_ids = set(
        await db.scalars(
            select(CredentialPoolCredential.pool_id)
            .join(
                ProviderCredential,
                ProviderCredential.id == CredentialPoolCredential.provider_credential_id,
            )
            .where(
                CredentialPoolCredential.org_id == org_id,
                CredentialPoolCredential.pool_id.in_(pool_ids),
                CredentialPoolCredential.is_active.is_(True),
                ProviderCredential.is_active.is_(True),
            )
            .distinct()
        )
    )

    return {
        key: _route_resource_from_rows(
            key=key,
            provider=providers.get(key.provider_id),
            pool=pools.get(key.credential_pool_id),
            model=models.get(key.model_offering_id),
            catalog_mapping=catalog_mappings.get(key.model_offering_id),
            pool_has_active_credential=key.credential_pool_id in ready_pool_ids,
        )
        for key in resources
    }


async def _get_provider(*, org_id: UUID, provider_id: UUID, db: AsyncSession) -> Provider | None:
    return await db.scalar(
        select(Provider).where(Provider.org_id == org_id, Provider.id == provider_id)
    )


async def _get_credential_pool(
    *,
    org_id: UUID,
    pool_id: UUID,
    db: AsyncSession,
) -> CredentialPool | None:
    return await db.scalar(
        select(CredentialPool).where(
            CredentialPool.org_id == org_id,
            CredentialPool.id == pool_id,
        )
    )


async def _get_provider_credential(
    *,
    org_id: UUID,
    credential_id: UUID,
    db: AsyncSession,
) -> ProviderCredential | None:
    return await db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.org_id == org_id,
            ProviderCredential.id == credential_id,
        )
    )


async def _get_model_offering(
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


def _route_resource_from_rows(
    *,
    key: ProviderRouteResourceKey,
    provider: Provider | None,
    pool: CredentialPool | None,
    model: ModelOffering | None,
    catalog_mapping: tuple[ProviderModelCatalogMapping, ModelCatalogEntry] | None,
    pool_has_active_credential: bool,
) -> ProviderRouteResource:
    mapping, catalog_entry = catalog_mapping if catalog_mapping is not None else (None, None)
    return ProviderRouteResource(
        provider_id=key.provider_id,
        provider_name=provider.name if provider else None,
        provider_is_active=provider.is_active if provider else False,
        provider_integration_capabilities=(
            _provider_integration_capabilities(provider) if provider else {}
        ),
        credential_pool_id=key.credential_pool_id,
        credential_pool_name=pool.name if pool else None,
        credential_pool_is_active=pool.is_active if pool else False,
        credential_pool_provider_id=pool.provider_id if pool else None,
        credential_pool_has_active_credential=pool_has_active_credential,
        model_offering_id=key.model_offering_id,
        model_provider_id=model.provider_id if model else None,
        provider_model_name=model.provider_model_name if model else None,
        model_is_active=model.is_active if model else False,
        effective_input_price_per_million_tokens=(
            _effective_price(
                manual=model.input_price_per_million_tokens,
                mapping=mapping.input_price_per_million_tokens if mapping else None,
                catalog=(
                    catalog_entry.input_price_per_million_tokens if catalog_entry else None
                ),
            )
            if model
            else None
        ),
        effective_output_price_per_million_tokens=(
            _effective_price(
                manual=model.output_price_per_million_tokens,
                mapping=mapping.output_price_per_million_tokens if mapping else None,
                catalog=(
                    catalog_entry.output_price_per_million_tokens if catalog_entry else None
                ),
            )
            if model
            else None
        ),
    )


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
