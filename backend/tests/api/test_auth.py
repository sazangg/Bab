from http.cookies import SimpleCookie

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import bootstrap
from app.core.security import decode_access_token


@pytest.mark.asyncio
async def test_mock_login_sets_refresh_cookie_and_returns_access_token(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
        )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"

    claims = decode_access_token(response.json()["access_token"])
    assert claims["sub"] == "00000000-0000-4000-8000-000000000001"
    assert claims["role"] == "super_admin"

    cookie = SimpleCookie(response.headers["set-cookie"])
    assert "bab_refresh_token" in cookie
    assert cookie["bab_refresh_token"]["httponly"]


@pytest.mark.asyncio
async def test_mock_login_rejects_invalid_password(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_mock_refresh_rotates_cookie(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
        )
        first_cookie = client.cookies["bab_refresh_token"]
        response = await client.post("/api/v1/auth/refresh")
        second_cookie = client.cookies["bab_refresh_token"]

    assert response.status_code == 200
    assert first_cookie
    assert second_cookie


@pytest.mark.asyncio
async def test_mock_logout_clears_cookie(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
        )
        response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert "bab_refresh_token" not in client.cookies
