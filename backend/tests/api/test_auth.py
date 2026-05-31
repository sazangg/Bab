from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

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
    assert claims["role"] == "org_owner"

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


@pytest.mark.asyncio
async def test_invite_acceptance_and_team_membership_flow(
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
        admin_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Research"},
            headers=admin_headers,
        )
        invite_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "member@example.com", "role": "org_viewer"},
            headers=admin_headers,
        )
        invite_token = parse_qs(urlparse(invite_response.json()["invite_url"]).query)["token"][0]
        accept_response = await client.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": invite_token,
                "name": "Member One",
                "password": "correct-password",
            },
        )
        members_response = await client.get("/api/v1/auth/members", headers=admin_headers)
        member = next(
            item for item in members_response.json() if item["email"] == "member@example.com"
        )
        add_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/members",
            json={"user_id": member["user_id"], "role": "team_member"},
            headers=admin_headers,
        )
        update_response = await client.patch(
            f"/api/v1/teams/{team_response.json()['id']}/members/{member['user_id']}",
            json={"role": "team_admin"},
            headers=admin_headers,
        )
        member_headers = {"Authorization": f"Bearer {accept_response.json()['access_token']}"}
        scoped_project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Scoped Project"},
            headers=member_headers,
        )
        other_team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Finance"},
            headers=admin_headers,
        )
        forbidden_project_response = await client.post(
            f"/api/v1/teams/{other_team_response.json()['id']}/projects",
            json={"name": "Forbidden Project"},
            headers=member_headers,
        )
        team_members_response = await client.get(
            f"/api/v1/teams/{team_response.json()['id']}/members",
            headers=admin_headers,
        )
        remove_response = await client.delete(
            f"/api/v1/teams/{team_response.json()['id']}/members/{member['user_id']}",
            headers=admin_headers,
        )
        audit_response = await client.get("/api/v1/auth/audit", headers=admin_headers)
        audit_export_response = await client.get(
            "/api/v1/auth/audit/export",
            params={"action": "team_member.added"},
            headers=admin_headers,
        )
        audit_verify_response = await client.get("/api/v1/auth/audit/verify", headers=admin_headers)

    assert team_response.status_code == 201
    assert invite_response.status_code == 201
    assert accept_response.status_code == 200
    assert add_response.status_code == 201
    assert add_response.json()["team_role"] == "team_member"
    assert update_response.status_code == 200
    assert update_response.json()["team_role"] == "team_admin"
    assert scoped_project_response.status_code == 201
    assert forbidden_project_response.status_code == 403
    assert team_members_response.status_code == 200
    assert [item["email"] for item in team_members_response.json()] == ["member@example.com"]
    assert remove_response.status_code == 204
    assert audit_response.status_code == 200
    audit_actions = {event["action"] for event in audit_response.json()}
    assert {
        "invite.created",
        "team_member.added",
        "team_member.role_updated",
        "team_member.removed",
    }.issubset(audit_actions)
    assert audit_export_response.status_code == 200
    assert audit_export_response.headers["content-type"].startswith("text/csv")
    assert "team_member.added" in audit_export_response.text
    assert "team_member.role_updated" not in audit_export_response.text
    assert "event_hash" in audit_export_response.text
    assert audit_verify_response.status_code == 200
    assert audit_verify_response.json()["valid"] is True, audit_verify_response.json()
    assert audit_verify_response.json()["checked_events"] >= 4


@pytest.mark.asyncio
async def test_admin_can_create_and_soft_deactivate_local_user(
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
        admin_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        create_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "viewer@example.com",
                "name": "Viewer User",
                "password": "viewer-password",
                "role": "org_viewer",
            },
            headers=admin_headers,
        )
        viewer_login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "viewer-password"},
        )
        deactivate_response = await client.patch(
            f"/api/v1/auth/members/{create_response.json()['user_id']}/status",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        inactive_login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "viewer-password"},
        )
        reactivate_response = await client.patch(
            f"/api/v1/auth/members/{create_response.json()['user_id']}/status",
            json={"status": "active"},
            headers=admin_headers,
        )

    assert create_response.status_code == 201
    assert create_response.json()["role"] == "org_viewer"
    assert viewer_login_response.status_code == 200
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["status"] == "inactive"
    assert inactive_login_response.status_code == 401
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_org_member_access_is_scoped_to_team_memberships(
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
        admin_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Scoped Team"},
            headers=admin_headers,
        )
        other_team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Other Team"},
            headers=admin_headers,
        )
        project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Scoped Project"},
            headers=admin_headers,
        )
        other_project_response = await client.post(
            f"/api/v1/teams/{other_team_response.json()['id']}/projects",
            json={"name": "Other Project"},
            headers=admin_headers,
        )
        create_member_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "scoped@example.com",
                "password": "scoped-password",
                "role": "org_member",
            },
            headers=admin_headers,
        )
        await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/members",
            json={"user_id": create_member_response.json()["user_id"], "role": "team_member"},
            headers=admin_headers,
        )
        member_login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "scoped@example.com", "password": "scoped-password"},
        )
        member_headers = {"Authorization": f"Bearer {member_login_response.json()['access_token']}"}
        teams_response = await client.get("/api/v1/teams", headers=member_headers)
        projects_response = await client.get("/api/v1/projects", headers=member_headers)
        own_project_response = await client.get(
            f"/api/v1/projects/{project_response.json()['id']}",
            headers=member_headers,
        )
        other_project_detail_response = await client.get(
            f"/api/v1/projects/{other_project_response.json()['id']}",
            headers=member_headers,
        )
        create_project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Denied Project"},
            headers=member_headers,
        )
        await client.patch(
            f"/api/v1/teams/{team_response.json()['id']}/members/{create_member_response.json()['user_id']}",
            json={"role": "team_admin"},
            headers=admin_headers,
        )
        admin_login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "scoped@example.com", "password": "scoped-password"},
        )
        team_admin_headers = {
            "Authorization": f"Bearer {admin_login_response.json()['access_token']}"
        }
        scoped_create_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Allowed Project"},
            headers=team_admin_headers,
        )
        other_create_response = await client.post(
            f"/api/v1/teams/{other_team_response.json()['id']}/projects",
            json={"name": "Still Denied Project"},
            headers=team_admin_headers,
        )

    assert create_member_response.status_code == 201
    assert create_member_response.json()["role"] == "org_member"
    assert teams_response.status_code == 200
    assert [team["id"] for team in teams_response.json()] == [team_response.json()["id"]]
    assert projects_response.status_code == 200
    assert [project["id"] for project in projects_response.json()] == [
        project_response.json()["id"]
    ]
    assert own_project_response.status_code == 200
    assert other_project_detail_response.status_code == 403
    assert create_project_response.status_code == 403
    assert scoped_create_response.status_code == 201
    assert other_create_response.status_code == 403


@pytest.mark.asyncio
async def test_last_owner_cannot_be_demoted_or_deactivated(
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
        admin_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        members_response = await client.get("/api/v1/auth/members", headers=admin_headers)
        owner = next(item for item in members_response.json() if item["role"] == "org_owner")
        demote_response = await client.patch(
            f"/api/v1/auth/members/{owner['user_id']}",
            json={"role": "org_admin"},
            headers=admin_headers,
        )
        deactivate_response = await client.patch(
            f"/api/v1/auth/members/{owner['user_id']}/status",
            json={"status": "inactive"},
            headers=admin_headers,
        )

    assert demote_response.status_code == 400
    assert deactivate_response.status_code == 400
