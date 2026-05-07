from http.cookies import SimpleCookie

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token, hash_password
from app.modules.audit.internal.models import AuditLog
from app.modules.auth.internal.models import Organization, RefreshToken, User


@pytest.mark.asyncio
async def test_login_sets_refresh_cookie_and_returns_access_token(
    app_client,
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Personal", slug="personal")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        User(
            org_id=org.id,
            email="admin@example.com",
            password_hash=hash_password("correct horse battery staple"),
            role="super_admin",
        )
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct horse battery staple"},
        )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"

    claims = decode_access_token(response.json()["access_token"])
    assert claims["sub"]
    assert claims["org_id"] == str(org.id)
    assert claims["role"] == "super_admin"

    cookie = SimpleCookie(response.headers["set-cookie"])
    assert "bab_refresh_token" in cookie
    assert cookie["bab_refresh_token"]["httponly"]

    refresh_token = await db_session.scalar(select(RefreshToken))
    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "auth.login_success")
    )

    assert refresh_token is not None
    assert refresh_token.revoked_at is None
    assert audit_log is not None


@pytest.mark.asyncio
async def test_login_rejects_invalid_password(app_client, db_session: AsyncSession) -> None:
    org = Organization(name="Personal", slug="personal")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        User(
            org_id=org.id,
            email="admin@example.com",
            password_hash=hash_password("correct horse battery staple"),
            role="super_admin",
        )
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong password"},
        )

    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.event == "auth.login_failed")
    )

    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert audit_log is not None


@pytest.mark.asyncio
async def test_refresh_rotates_refresh_cookie(app_client, db_session: AsyncSession) -> None:
    org = Organization(name="Personal", slug="personal")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        User(
            org_id=org.id,
            email="admin@example.com",
            password_hash=hash_password("correct horse battery staple"),
            role="super_admin",
        )
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct horse battery staple"},
        )
        first_cookie = client.cookies["bab_refresh_token"]
        refresh_response = await client.post("/api/v1/auth/refresh")
        second_cookie = client.cookies["bab_refresh_token"]

    tokens = list(await db_session.scalars(select(RefreshToken)))

    assert login_response.status_code == 200
    assert refresh_response.status_code == 200
    assert first_cookie != second_cookie
    assert len(tokens) == 2
    assert sum(token.revoked_at is not None for token in tokens) == 1


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token_and_clears_cookie(
    app_client,
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Personal", slug="personal")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        User(
            org_id=org.id,
            email="admin@example.com",
            password_hash=hash_password("correct horse battery staple"),
            role="super_admin",
        )
    )
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct horse battery staple"},
        )
        response = await client.post("/api/v1/auth/logout")

    refresh_token = await db_session.scalar(select(RefreshToken))
    audit_log = await db_session.scalar(select(AuditLog).where(AuditLog.event == "auth.logout"))

    assert response.status_code == 204
    assert refresh_token is not None
    assert refresh_token.revoked_at is not None
    assert audit_log is not None
