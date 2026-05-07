import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.modules.auth.models import Organization, User
from app.modules.setup.internal.models import SetupLock


@pytest.mark.asyncio
async def test_setup_status_is_required_when_no_user_exists(app_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/setup/status")

    assert response.status_code == 200
    assert response.json() == {"setup_required": True}


@pytest.mark.asyncio
async def test_setup_creates_first_admin(app_client, db_session: AsyncSession) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/setup",
            json={
                "email": "admin@example.com",
                "password": "correct horse battery staple",
                "organization_name": "Personal",
            },
        )

    assert response.status_code == 201
    assert response.json() == {
        "email": "admin@example.com",
        "organization_name": "Personal",
        "role": "super_admin",
    }

    user = await db_session.scalar(select(User).where(User.email == "admin@example.com"))
    org = await db_session.scalar(select(Organization).where(Organization.name == "Personal"))

    assert user is not None
    assert org is not None
    assert user.org_id == org.id
    assert user.role == "super_admin"
    assert verify_password("correct horse battery staple", user.password_hash)


@pytest.mark.asyncio
async def test_setup_is_disabled_after_first_user_exists(app_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        first_response = await client.post(
            "/api/v1/setup",
            json={
                "email": "admin@example.com",
                "password": "correct horse battery staple",
                "organization_name": "Personal",
            },
        )
        status_response = await client.get("/api/v1/setup/status")
        second_response = await client.post(
            "/api/v1/setup",
            json={
                "email": "other@example.com",
                "password": "correct horse battery staple",
                "organization_name": "Other",
            },
        )

    assert first_response.status_code == 201
    assert status_response.json() == {"setup_required": False}
    assert second_response.status_code == 409


@pytest.mark.asyncio
async def test_setup_returns_conflict_when_setup_lock_already_exists(
    app_client,
    db_session: AsyncSession,
) -> None:
    db_session.add(SetupLock())
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/setup",
            json={
                "email": "admin@example.com",
                "password": "correct horse battery staple",
                "organization_name": "Personal",
            },
        )

    assert response.status_code == 409
