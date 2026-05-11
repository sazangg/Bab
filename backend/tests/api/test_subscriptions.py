import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project, Subscription
from app.modules.providers.internal.models import Provider, ProviderKey


async def _create_user(db_session: AsyncSession, *, role: str = "super_admin") -> User:
    org = Organization(name=f"Subscription API Org {role}", slug=f"subscription-api-{role}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"subscription-api-{role}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


async def _create_provider_key(db_session: AsyncSession, user: User) -> ProviderKey:
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="legacy",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.flush()
    provider_key = ProviderKey(
        org_id=user.org_id,
        provider_id=provider.id,
        name="Production",
        key_prefix="sk-p...",
        api_key_encrypted="encrypted",
    )
    db_session.add(provider_key)
    await db_session.commit()
    return provider_key


@pytest.mark.asyncio
async def test_super_admin_can_create_and_list_subscriptions(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/api/v1/subscriptions",
            headers=_auth_headers(user),
            json={"name": "Default AI", "description": "Shared access"},
        )
        list_response = await client.get("/api/v1/subscriptions", headers=_auth_headers(user))

    assert create_response.status_code == 201
    assert create_response.json()["name"] == "Default AI"
    assert list_response.status_code == 200
    assert [subscription["id"] for subscription in list_response.json()] == [
        create_response.json()["id"]
    ]


@pytest.mark.asyncio
async def test_non_admin_cannot_create_subscription(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, role="team_manager")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/subscriptions",
            headers=_auth_headers(user),
            json={"name": "Default AI"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_can_attach_provider_key_to_subscription(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider_key = await _create_provider_key(db_session, user)
    subscription = Subscription(org_id=user.org_id, name="Default AI")
    db_session.add(subscription)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            f"/api/v1/subscriptions/{subscription.id}/provider-keys",
            headers=_auth_headers(user),
            json={"provider_key_id": str(provider_key.id), "priority": 20},
        )
        list_response = await client.get(
            f"/api/v1/subscriptions/{subscription.id}/provider-keys",
            headers=_auth_headers(user),
        )

    assert create_response.status_code == 201
    assert create_response.json()["provider_key_id"] == str(provider_key.id)
    assert create_response.json()["priority"] == 20
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [create_response.json()["id"]]


@pytest.mark.asyncio
async def test_super_admin_can_grant_subscription_to_project(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = Project(org_id=user.org_id, created_by=user.id, name="Inbox Assistant")
    subscription = Subscription(org_id=user.org_id, name="Default AI")
    db_session.add_all([project, subscription])
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            f"/api/v1/projects/{project.id}/subscription-access",
            headers=_auth_headers(user),
            json={"subscription_id": str(subscription.id), "priority": 5},
        )
        list_response = await client.get(
            f"/api/v1/projects/{project.id}/subscription-access",
            headers=_auth_headers(user),
        )

    assert create_response.status_code == 201
    assert create_response.json()["subscription_id"] == str(subscription.id)
    assert create_response.json()["priority"] == 5
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [create_response.json()["id"]]
