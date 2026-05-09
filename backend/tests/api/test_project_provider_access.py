import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.audit.internal.models import AuditLog
from app.modules.auth.internal.models import Organization, User
from app.modules.keys.internal.models import Project, ProjectProviderAccess
from app.modules.providers.internal.models import Provider


async def _create_user(db_session: AsyncSession, *, role: str = "super_admin") -> User:
    org = Organization(name=f"Access Org {role}", slug=f"access-org-{role}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"access-{role}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _create_project_and_provider(
    db_session: AsyncSession,
    user: User,
) -> tuple[Project, Provider]:
    project = Project(org_id=user.org_id, created_by=user.id, name="Inbox Assistant")
    provider = Provider(
        org_id=user.org_id,
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_encrypted="encrypted",
        adapter_type="openai_compat",
    )
    db_session.add_all([project, provider])
    await db_session.commit()
    return project, provider


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_super_admin_can_grant_provider_access_to_project(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project, provider = await _create_project_and_provider(db_session, user)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/provider-access",
            headers=_auth_headers(user),
            json={"provider_id": str(provider.id), "allowed_models": ["gpt-5.4", "gpt-5.4-mini"]},
        )

    body = response.json()
    access = await db_session.scalar(select(ProjectProviderAccess))
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "project_provider_access.granted")
    )

    assert response.status_code == 201
    assert body["project_id"] == str(project.id)
    assert body["provider_id"] == str(provider.id)
    assert body["allowed_models"] == ["gpt-5.4", "gpt-5.4-mini"]
    assert access is not None
    assert access.org_id == user.org_id
    assert audit_log is not None


@pytest.mark.asyncio
async def test_null_allowed_models_grants_all_models(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project, provider = await _create_project_and_provider(db_session, user)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/provider-access",
            headers=_auth_headers(user),
            json={"provider_id": str(provider.id), "allowed_models": None},
        )

    assert response.status_code == 201
    assert response.json()["allowed_models"] is None


@pytest.mark.asyncio
async def test_empty_allowed_models_is_rejected(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project, provider = await _create_project_and_provider(db_session, user)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/provider-access",
            headers=_auth_headers(user),
            json={"provider_id": str(provider.id), "allowed_models": []},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_non_admin_cannot_grant_provider_access(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, role="team_manager")
    project, provider = await _create_project_and_provider(db_session, user)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{project.id}/provider-access",
            headers=_auth_headers(user),
            json={"provider_id": str(provider.id), "allowed_models": None},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_authenticated_user_can_list_project_provider_access(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project, provider = await _create_project_and_provider(db_session, user)
    db_session.add(
        ProjectProviderAccess(
            org_id=user.org_id,
            project_id=project.id,
            provider_id=provider.id,
            allowed_models=["gpt-5.4"],
        )
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/projects/{project.id}/provider-access",
            headers=_auth_headers(user),
        )

    assert response.status_code == 200
    assert response.json()[0]["provider_id"] == str(provider.id)


@pytest.mark.asyncio
async def test_super_admin_can_update_provider_access_models(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project, provider = await _create_project_and_provider(db_session, user)
    access = ProjectProviderAccess(
        org_id=user.org_id,
        project_id=project.id,
        provider_id=provider.id,
        allowed_models=["gpt-5.4"],
    )
    db_session.add(access)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/api/v1/projects/{project.id}/provider-access/{provider.id}",
            headers=_auth_headers(user),
            json={"allowed_models": ["gpt-5.4-mini"]},
        )

    await db_session.refresh(access)

    assert response.status_code == 200
    assert response.json()["allowed_models"] == ["gpt-5.4-mini"]
    assert access.allowed_models == ["gpt-5.4-mini"]


@pytest.mark.asyncio
async def test_super_admin_can_revoke_provider_access(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project, provider = await _create_project_and_provider(db_session, user)
    access = ProjectProviderAccess(
        org_id=user.org_id,
        project_id=project.id,
        provider_id=provider.id,
        allowed_models=None,
    )
    db_session.add(access)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v1/projects/{project.id}/provider-access/{provider.id}",
            headers=_auth_headers(user),
        )

    remaining = await db_session.scalar(select(ProjectProviderAccess))

    assert response.status_code == 204
    assert remaining is None
