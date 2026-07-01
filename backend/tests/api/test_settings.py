import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import bootstrap


@pytest.mark.asyncio
async def test_logo_upload_rejects_svg(
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
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
        )
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        response = await client.post(
            "/api/v1/settings/organization-logo",
            files={"file": ("logo.svg", b"<svg />", "image/svg+xml")},
            headers=headers,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "logo must be a valid png, jpg, or webp image"


@pytest.mark.asyncio
async def test_settings_patch_rejects_null_for_non_nullable_field(
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
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
        )
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        response = await client.patch(
            "/api/v1/settings",
            json={"default_request_timeout_seconds": None},
            headers=headers,
        )

    assert response.status_code == 422
