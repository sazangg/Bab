import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decrypt, encrypt, hash_password
from app.modules.audit.internal.models import AuditLog
from app.modules.auth.internal.models import Organization, User
from app.modules.providers.internal.models import Provider, ProviderKey, ProviderModel


async def _create_user(db_session: AsyncSession, *, role: str = "super_admin") -> User:
    org = Organization(name=f"Org {role}", slug=f"org-{role}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{role}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_super_admin_can_create_provider(app_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/providers",
            headers=_auth_headers(user),
            json={
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-provider-secret",
                "adapter_type": "openai_compat",
            },
        )

    body = response.json()
    provider = await db_session.scalar(select(Provider))
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "provider.created")
    )

    assert response.status_code == 201
    assert body["name"] == "OpenAI"
    assert body["base_url"] == "https://api.openai.com/v1"
    assert "api_key" not in body
    assert provider is not None
    assert provider.org_id == user.org_id
    assert provider.api_key_encrypted != "sk-provider-secret"
    assert decrypt(provider.api_key_encrypted) == "sk-provider-secret"
    assert audit_log is not None
    assert audit_log.actor_user_id == user.id


@pytest.mark.asyncio
async def test_non_admin_cannot_create_provider(app_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session, role="team_manager")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/providers",
            headers=_auth_headers(user),
            json={
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-provider-secret",
            },
        )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_authenticated_user_can_list_scoped_providers(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    other_user = await _create_user(db_session, role="org_admin")
    db_session.add_all(
        [
            Provider(
                org_id=user.org_id,
                name="OpenAI",
                base_url="https://api.openai.com/v1",
                api_key_encrypted="encrypted",
                adapter_type="openai_compat",
            ),
            Provider(
                org_id=other_user.org_id,
                name="Other",
                base_url="https://other.example/v1",
                api_key_encrypted="encrypted",
                adapter_type="openai_compat",
            ),
        ]
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/providers", headers=_auth_headers(user))

    assert response.status_code == 200
    assert [provider["name"] for provider in response.json()] == ["OpenAI"]


@pytest.mark.asyncio
async def test_super_admin_can_update_provider_without_returning_secret(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="old-secret",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/providers/{provider.id}",
            headers=_auth_headers(user),
            json={"name": "OpenAI Updated", "api_key": "new-secret"},
        )

    await db_session.refresh(provider)
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "provider.credential_changed")
    )

    assert response.status_code == 200
    assert response.json()["name"] == "OpenAI Updated"
    assert "api_key" not in response.json()
    assert decrypt(provider.api_key_encrypted) == "new-secret"
    assert audit_log is not None


@pytest.mark.asyncio
async def test_super_admin_can_deactivate_provider(app_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="encrypted",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v1/providers/{provider.id}",
            headers=_auth_headers(user),
        )

    await db_session.refresh(provider)

    assert response.status_code == 204
    assert provider.is_active is False


@pytest.mark.asyncio
async def test_super_admin_can_create_and_list_provider_keys(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="legacy",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            f"/api/v1/providers/{provider.id}/keys",
            headers=_auth_headers(user),
            json={"name": "Production", "api_key": "sk-provider-secret", "priority": 10},
        )
        list_response = await client.get(
            f"/api/v1/providers/{provider.id}/keys",
            headers=_auth_headers(user),
        )

    created = create_response.json()
    stored_key = await db_session.scalar(select(ProviderKey))

    assert create_response.status_code == 201
    assert created["name"] == "Production"
    assert created["key_prefix"] == "sk-p..."
    assert created["priority"] == 10
    assert "api_key" not in created
    assert "api_key_encrypted" not in created
    assert stored_key is not None
    assert decrypt(stored_key.api_key_encrypted) == "sk-provider-secret"
    assert list_response.status_code == 200
    assert [key["id"] for key in list_response.json()] == [created["id"]]


@pytest.mark.asyncio
async def test_non_admin_cannot_create_provider_key(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, role="team_manager")
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="legacy",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/providers/{provider.id}/keys",
            headers=_auth_headers(user),
            json={"name": "Production", "api_key": "sk-provider-secret"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_can_create_and_list_provider_models(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="legacy",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            f"/api/v1/providers/{provider.id}/models",
            headers=_auth_headers(user),
            json={"provider_model_name": "gpt-5.4-mini", "alias": "fast"},
        )
        list_response = await client.get(
            f"/api/v1/providers/{provider.id}/models",
            headers=_auth_headers(user),
        )

    created = create_response.json()
    stored_model = await db_session.scalar(select(ProviderModel))

    assert create_response.status_code == 201
    assert created["provider_model_name"] == "gpt-5.4-mini"
    assert created["alias"] == "fast"
    assert stored_model is not None
    assert list_response.status_code == 200
    assert [model["id"] for model in list_response.json()] == [created["id"]]


@pytest.mark.asyncio
async def test_super_admin_can_sync_provider_models(
    app_client,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(db_session)
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.example.test/v1",
        api_key_encrypted="legacy",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.flush()
    db_session.add(
        ProviderKey(
            org_id=user.org_id,
            provider_id=provider.id,
            name="Production",
            key_prefix="sk-p...",
            api_key_encrypted=encrypt("provider-secret"),
        )
    )
    await db_session.commit()

    real_async_client = httpx.AsyncClient

    def mock_client_factory(**_kwargs):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://api.example.test/v1/models"
            assert request.headers["authorization"] == "Bearer provider-secret"
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt-5.4-mini"}, {"id": "gpt-5.4"}]},
            )

        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.api.v1.routes.providers.httpx.AsyncClient", mock_client_factory)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/providers/{provider.id}/models/sync",
            headers=_auth_headers(user),
        )

    assert response.status_code == 200
    assert [model["provider_model_name"] for model in response.json()] == [
        "gpt-5.4",
        "gpt-5.4-mini",
    ]
