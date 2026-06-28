from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade as providers_facade
from app.modules.providers.internal.models import ModelCatalogEntry, ProviderModelCatalogMapping
from app.modules.providers.schemas import (
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    ModelMetadataSyncMode,
    UpdateProviderModelOfferingRequest,
)
from app.modules.workspace.internal.models import Organization


async def test_manual_model_metadata_survives_catalog_sync(db_session: AsyncSession) -> None:
    org = Organization(name="Model Sync Org", slug="model-sync")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.openai.com/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Production", api_key="provider-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-5.4"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        synced = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
        )
        assert synced.status == "success"
        assert synced.summary.added == 1
        model = synced.models[0]
        assert model.metadata_source == "catalog"
        assert model.metadata_last_synced_at is not None

        edited = await providers_facade.update_model_offering(
            provider_id=provider.id,
            model_offering_id=model.id,
            payload=UpdateProviderModelOfferingRequest(
                context_window=12345,
                input_price_per_million_tokens=123,
                output_price_per_million_tokens=456,
                cached_input_price_per_million_tokens=78,
                input_modalities=["text"],
                output_modalities=["text"],
                capabilities={"chat": True, "streaming": False},
            ),
            actor=actor,
            scope=scope,
            db=db_session,
        )
        assert edited.metadata_source == "manual"

        synced_again = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
        )

    assert synced_again.summary.updated == 1
    model_again = synced_again.models[0]
    assert model_again.context_window == 12345
    assert model_again.input_price_per_million_tokens == 123
    assert model_again.output_price_per_million_tokens == 456
    assert model_again.cached_input_price_per_million_tokens == 78
    assert model_again.input_modalities == ["text"]
    assert model_again.output_modalities == ["text"]
    assert model_again.capabilities["streaming"] is False
    assert model_again.metadata_source == "manual"
    assert model_again.metadata_last_synced_at is not None


async def test_overwrite_catalog_sync_replaces_manual_model_metadata(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Model Overwrite Org", slug="model-overwrite")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.openai.com/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Production", api_key="provider-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-5.4"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        synced = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
        )
        model = synced.models[0]
        await providers_facade.update_model_offering(
            provider_id=provider.id,
            model_offering_id=model.id,
            payload=UpdateProviderModelOfferingRequest(
                context_window=12345,
                input_modalities=["text"],
                output_modalities=["text"],
                capabilities={"chat": True, "streaming": False},
            ),
            actor=actor,
            scope=scope,
            db=db_session,
        )

        overwritten = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.overwrite_catalog,
        )

    model_again = overwritten.models[0]
    assert model_again.context_window == 1_000_000
    assert model_again.input_modalities == ["text", "vision"]
    assert model_again.output_modalities == ["text"]
    assert model_again.capabilities["streaming"] is True
    assert model_again.metadata_source == "catalog"


async def test_fill_missing_sync_keeps_unknown_provider_only_models_safe(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Unknown Model Org", slug="unknown-model")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="Custom OpenAI Compatible",
            base_url="https://api.example.test/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Production", api_key="provider-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "custom-chat-model"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        synced = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.overwrite_catalog,
        )

    model = synced.models[0]
    assert model.provider_model_name == "custom-chat-model"
    assert model.metadata_source == "provider"
    assert model.input_modalities == ["text"]
    assert model.output_modalities == ["text"]
    assert model.capabilities == {"chat": True}
    mapping = await db_session.scalar(
        select(ProviderModelCatalogMapping).where(
            ProviderModelCatalogMapping.provider_model_offering_id == model.id
        )
    )
    assert mapping is None


async def test_replace_sync_reports_disabled_and_reactivated_models(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Sync Summary Org", slug="sync-summary")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="OpenAI", base_url="https://api.openai.com/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Production", api_key="provider-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    model_ids = [["model-a", "model-b"], ["model-a"], ["model-a", "model-b"]]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": item} for item in model_ids.pop(0)]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        first = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
            sync_mode="replace",
        )
        second = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
            sync_mode="replace",
        )
        third = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
            sync_mode="replace",
        )

    assert first.summary.added == 2
    assert second.summary.disabled == 1
    assert second.summary.unchanged == 1
    assert third.summary.reactivated == 1


async def test_catalog_pricing_tracks_effective_price_and_manual_overrides(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Pricing Catalog Org", slug="pricing-catalog")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.openai.com/v1",
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Production", api_key="provider-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        synced = await providers_facade.sync_model_offerings(
            provider_id=provider.id,
            actor=actor,
            scope=scope,
            db=db_session,
            http_client=http_client,
            metadata_mode=ModelMetadataSyncMode.fill_missing,
        )

    model = synced.models[0]
    assert model.effective_input_price_per_million_tokens == 15
    assert model.effective_output_price_per_million_tokens == 60
    assert model.pricing_source == "catalog_mapping"
    mapping = await db_session.scalar(
        select(ProviderModelCatalogMapping).where(
            ProviderModelCatalogMapping.provider_model_offering_id == model.id
        )
    )
    assert mapping is not None
    catalog_entry = await db_session.scalar(
        select(ModelCatalogEntry).where(ModelCatalogEntry.id == mapping.catalog_entry_id)
    )
    assert catalog_entry is not None
    assert catalog_entry.canonical_name == "gpt-4o-mini"
    assert catalog_entry.provider_family == "openai"
    assert catalog_entry.pricing_currency == "USD"
    assert catalog_entry.pricing_unit == "million_tokens"

    edited = await providers_facade.update_model_offering(
        provider_id=provider.id,
        model_offering_id=model.id,
        payload=UpdateProviderModelOfferingRequest(input_price_per_million_tokens=25),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    assert edited.effective_input_price_per_million_tokens == 25
    assert edited.effective_output_price_per_million_tokens == 60
    assert edited.pricing_source == "manual"
