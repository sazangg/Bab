import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import bootstrap


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_limit_policy_can_be_created_and_assigned_to_org(
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
        headers = await _login(client)
        policy_response = await client.post(
            "/api/v1/policies/limits",
            headers=headers,
            json={
                "name": "Org monthly budget",
                "rules": [
                    {
                        "name": "Monthly budget",
                        "limit_type": "budget_cents",
                        "limit_value": 500_000,
                        "interval_unit": "month",
                    }
                ],
            },
        )
        assert policy_response.status_code == 201
        policy_id = policy_response.json()["id"]

        assignment_response = await client.post(
            "/api/v1/policies/assignments",
            headers=headers,
            json={
                "policy_type": "limit",
                "limit_policy_id": policy_id,
                "scope_type": "org",
            },
        )
        assert assignment_response.status_code == 201

        list_response = await client.get("/api/v1/policies/limits", headers=headers)

    assert list_response.status_code == 200
    assert list_response.json()[0]["name"] == "Org monthly budget"


@pytest.mark.asyncio
async def test_viewer_can_read_but_not_create_policies(
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
        admin_headers = await _login(client)
        create_member = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "viewer@example.com",
                "password": "viewer-password",
                "role": "org_viewer",
            },
        )
        assert create_member.status_code == 201
        viewer_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "viewer-password"},
        )
        viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}

        read_response = await client.get("/api/v1/policies/access", headers=viewer_headers)
        write_response = await client.post(
            "/api/v1/policies/limits",
            headers=viewer_headers,
            json={
                "name": "Viewer budget",
                "rules": [
                    {
                        "name": "Monthly budget",
                        "limit_type": "budget_cents",
                        "limit_value": 500_000,
                        "interval_unit": "month",
                    }
                ],
            },
        )

    assert read_response.status_code == 200
    assert write_response.status_code == 403
