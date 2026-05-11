import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.security import decrypt, hash_password
from app.modules.auth.internal.models import Organization, User
from app.modules.providers import facade as providers_facade
from app.modules.providers.internal.models import ProviderKey
from app.modules.providers.schemas import (
    CreateProviderKeyRequest,
    CreateProviderModelRequest,
    CreateProviderRequest,
)


async def _create_user(db_session: AsyncSession) -> User:
    org = Organization(name="Provider Resources Org", slug="provider-resources")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email="provider-resources@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role="super_admin",
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_provider_key_is_created_as_encrypted_child_resource(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    scope = Scope(org_id=user.org_id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="legacy-secret",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )

    provider_key = await providers_facade.create_provider_key(
        provider_id=provider.id,
        payload=CreateProviderKeyRequest(name="Production", api_key="sk-provider-secret"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    provider_keys = await providers_facade.list_provider_keys(
        provider_id=provider.id,
        scope=scope,
        db=db_session,
    )
    stored_key = await db_session.scalar(
        select(ProviderKey).where(ProviderKey.id == provider_key.id)
    )

    assert provider_key.provider_id == provider.id
    assert provider_key.name == "Production"
    assert provider_key.key_prefix == "sk-p..."
    assert provider_key.is_active is True
    assert stored_key is not None
    assert stored_key.api_key_encrypted != "sk-provider-secret"
    assert decrypt(stored_key.api_key_encrypted) == "sk-provider-secret"
    assert [key.id for key in provider_keys] == [provider_key.id]


async def test_provider_model_alias_is_unique_per_provider(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    scope = Scope(org_id=user.org_id)
    openai = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="legacy-openai-secret",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    mistral = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key="legacy-mistral-secret",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )

    openai_model = await providers_facade.create_provider_model(
        provider_id=openai.id,
        payload=CreateProviderModelRequest(provider_model_name="gpt-5.4-mini", alias="fast"),
        actor=user,
        scope=scope,
        db=db_session,
    )
    mistral_model = await providers_facade.create_provider_model(
        provider_id=mistral.id,
        payload=CreateProviderModelRequest(
            provider_model_name="mistral-small-latest",
            alias="fast",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )

    assert openai_model.alias == "fast"
    assert mistral_model.alias == "fast"
    assert openai_model.provider_id != mistral_model.provider_id


async def test_sync_provider_models_upserts_upstream_models(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    scope = Scope(org_id=user.org_id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(
            name="OpenAI",
            base_url="https://api.example.test/v1",
            api_key="legacy-secret",
        ),
        actor=user,
        scope=scope,
        db=db_session,
    )
    await providers_facade.create_provider_key(
        provider_id=provider.id,
        payload=CreateProviderKeyRequest(name="Production", api_key="provider-secret"),
        actor=user,
        scope=scope,
        db=db_session,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.test/v1/models"
        assert request.headers["authorization"] == "Bearer provider-secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-5.4-mini"},
                    {"id": "gpt-5.4"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        synced = await providers_facade.sync_provider_models(
            provider_id=provider.id,
            actor=user,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )
        synced_again = await providers_facade.sync_provider_models(
            provider_id=provider.id,
            actor=user,
            scope=scope,
            db=db_session,
            http_client=http_client,
        )

    assert [model.provider_model_name for model in synced] == ["gpt-5.4", "gpt-5.4-mini"]
    assert [model.id for model in synced_again] == [model.id for model in synced]
