from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, hash_token
from app.modules.audit.internal.models import AuditLog
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.providers.internal.models import Provider


async def _create_user(db_session: AsyncSession, *, role: str = "super_admin") -> User:
    org = Organization(name=f"Key Org {role}", slug=f"key-org-{role}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"key-{role}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _create_project(db_session: AsyncSession, user: User) -> Project:
    project = Project(org_id=user.org_id, created_by=user.id, name="Inbox Assistant")
    db_session.add(project)
    await db_session.commit()
    return project


async def _create_provider(db_session: AsyncSession, user: User) -> Provider:
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
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
async def test_super_admin_can_create_virtual_key(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, user)
    provider = await _create_provider(db_session, user)
    expires_at = datetime.now(UTC) + timedelta(days=30)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/keys",
            headers=_auth_headers(user),
            json={
                "name": "Local dev",
                "expires_at": expires_at.isoformat(),
                "restrictions": [
                    {"provider_id": str(provider.id), "allowed_models": ["gpt-5.4-mini"]}
                ],
            },
        )

    body = response.json()
    virtual_key = await db_session.scalar(select(VirtualKey))
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "virtual_key.created")
    )

    assert response.status_code == 201
    assert body["key"].startswith("bab-sk-")
    assert body["key_prefix"] == body["key"][:16]
    assert "key_hash" not in body
    assert virtual_key is not None
    assert virtual_key.key_hash == hash_token(body["key"])
    assert virtual_key.key_hash != body["key"]
    assert virtual_key.project_id == project.id
    assert audit_log is not None


@pytest.mark.asyncio
async def test_created_key_raw_value_is_not_returned_when_listing(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, user)
    virtual_key = VirtualKey(
        org_id=user.org_id,
        project_id=project.id,
        name="Local dev",
        key_hash=hash_token("bab-sk-secret"),
        key_prefix="bab-sk-secret"[:16],
        restrictions=None,
    )
    db_session.add(virtual_key)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/projects/{project.id}/keys",
            headers=_auth_headers(user),
        )

    body = response.json()

    assert response.status_code == 200
    assert body[0]["name"] == "Local dev"
    assert "key" not in body[0]
    assert "key_hash" not in body[0]


@pytest.mark.asyncio
async def test_non_admin_cannot_create_virtual_key(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, role="team_manager")
    project = await _create_project(db_session, user)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/keys",
            headers=_auth_headers(user),
            json={"name": "Nope"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_can_update_virtual_key_restrictions(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, user)
    provider = await _create_provider(db_session, user)
    virtual_key = VirtualKey(
        org_id=user.org_id,
        project_id=project.id,
        name="Local dev",
        key_hash=hash_token("bab-sk-secret"),
        key_prefix="bab-sk-secret"[:16],
        restrictions=None,
    )
    db_session.add(virtual_key)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/projects/{project.id}/keys/{virtual_key.id}",
            headers=_auth_headers(user),
            json={
                "name": "Production",
                "restrictions": [{"provider_id": str(provider.id), "allowed_models": None}],
            },
        )

    await db_session.refresh(virtual_key)
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "virtual_key.restrictions_updated")
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Production"
    assert virtual_key.restrictions == [{"provider_id": str(provider.id), "allowed_models": None}]
    assert audit_log is not None


@pytest.mark.asyncio
async def test_super_admin_can_revoke_virtual_key(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, user)
    virtual_key = VirtualKey(
        org_id=user.org_id,
        project_id=project.id,
        name="Local dev",
        key_hash=hash_token("bab-sk-secret"),
        key_prefix="bab-sk-secret"[:16],
        restrictions=None,
    )
    db_session.add(virtual_key)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v1/projects/{project.id}/keys/{virtual_key.id}",
            headers=_auth_headers(user),
        )

    await db_session.refresh(virtual_key)

    assert response.status_code == 204
    assert virtual_key.revoked_at is not None
