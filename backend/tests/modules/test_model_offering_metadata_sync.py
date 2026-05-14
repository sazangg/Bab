from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import (
    CreateProviderCredentialRequest,
    CreateProviderRequest,
    UpdateModelOfferingRequest,
)


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
        )
        model = synced[0]
        assert model.metadata_source == "catalog"
        assert model.metadata_last_synced_at is not None

        edited = await providers_facade.update_model_offering(
            provider_id=provider.id,
            model_offering_id=model.id,
            payload=UpdateModelOfferingRequest(
                context_window=12345,
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
        )

    model_again = synced_again[0]
    assert model_again.context_window == 12345
    assert model_again.input_modalities == ["text"]
    assert model_again.output_modalities == ["text"]
    assert model_again.capabilities["streaming"] is False
    assert model_again.metadata_source == "manual"
    assert model_again.metadata_last_synced_at is not None
