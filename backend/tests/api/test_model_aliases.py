import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.audit.internal.models import AuditLog
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import ModelAlias
from app.modules.providers.internal.models import Provider


async def _create_user(db_session: AsyncSession, *, role: str = "super_admin") -> User:
    org = Organization(name=f"Alias Org {role}", slug=f"alias-org-{role}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"alias-{role}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _create_provider(
    db_session: AsyncSession, user: User, *, name: str = "OpenAI"
) -> Provider:
    provider = Provider(
        org_id=user.org_id,
        name=name,
        base_url="https://api.openai.com/v1",
        api_key_encrypted="encrypted",
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.commit()
    return provider


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_super_admin_can_create_model_alias(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider = await _create_provider(db_session, user)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/model-aliases",
            headers=_auth_headers(user),
            json={
                "alias": "fast-default",
                "provider_id": str(provider.id),
                "provider_model": "gpt-5.4-mini",
            },
        )

    body = response.json()
    model_alias = await db_session.scalar(select(ModelAlias))
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "model_alias.created")
    )

    assert response.status_code == 201
    assert body["alias"] == "fast-default"
    assert body["provider_id"] == str(provider.id)
    assert body["provider_model"] == "gpt-5.4-mini"
    assert model_alias is not None
    assert model_alias.org_id == user.org_id
    assert audit_log is not None


@pytest.mark.asyncio
async def test_duplicate_model_alias_in_same_org_is_rejected(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider = await _create_provider(db_session, user)
    db_session.add(
        ModelAlias(
            org_id=user.org_id,
            alias="fast-default",
            provider_id=provider.id,
            provider_model="gpt-5.4-mini",
        )
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/model-aliases",
            headers=_auth_headers(user),
            json={
                "alias": "fast-default",
                "provider_id": str(provider.id),
                "provider_model": "gpt-5.4",
            },
        )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_non_admin_cannot_create_model_alias(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, role="team_manager")
    provider = await _create_provider(db_session, user)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/model-aliases",
            headers=_auth_headers(user),
            json={
                "alias": "fast-default",
                "provider_id": str(provider.id),
                "provider_model": "gpt-5.4-mini",
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_authenticated_user_can_list_scoped_model_aliases(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    other_user = await _create_user(db_session, role="org_admin")
    provider = await _create_provider(db_session, user)
    other_provider = await _create_provider(db_session, other_user, name="Other")
    db_session.add_all(
        [
            ModelAlias(
                org_id=user.org_id,
                alias="mine",
                provider_id=provider.id,
                provider_model="gpt-5.4",
            ),
            ModelAlias(
                org_id=other_user.org_id,
                alias="other",
                provider_id=other_provider.id,
                provider_model="other-model",
            ),
        ]
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/model-aliases", headers=_auth_headers(user))

    assert response.status_code == 200
    assert [alias["alias"] for alias in response.json()] == ["mine"]


@pytest.mark.asyncio
async def test_super_admin_can_update_model_alias(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider = await _create_provider(db_session, user)
    model_alias = ModelAlias(
        org_id=user.org_id,
        alias="fast-default",
        provider_id=provider.id,
        provider_model="gpt-5.4-mini",
    )
    db_session.add(model_alias)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/model-aliases/{model_alias.id}",
            headers=_auth_headers(user),
            json={"alias": "balanced-default", "provider_model": "gpt-5.4"},
        )

    await db_session.refresh(model_alias)
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "model_alias.updated")
    )

    assert response.status_code == 200
    assert response.json()["alias"] == "balanced-default"
    assert model_alias.alias == "balanced-default"
    assert model_alias.provider_model == "gpt-5.4"
    assert audit_log is not None


@pytest.mark.asyncio
async def test_super_admin_can_deactivate_model_alias(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    provider = await _create_provider(db_session, user)
    model_alias = ModelAlias(
        org_id=user.org_id,
        alias="fast-default",
        provider_id=provider.id,
        provider_model="gpt-5.4-mini",
    )
    db_session.add(model_alias)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v1/model-aliases/{model_alias.id}",
            headers=_auth_headers(user),
        )

    await db_session.refresh(model_alias)

    assert response.status_code == 204
    assert model_alias.is_active is False
