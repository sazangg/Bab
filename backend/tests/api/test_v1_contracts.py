import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes import health as health_routes
from app.core import bootstrap
from app.modules.auth.internal.models import Organization, Team, User
from app.modules.providers.internal.models import Provider
from app.modules.settings.internal.models import OrganizationSettings


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_runtime_info_migration_state_shape_uses_public_keys(
    app_client,
    monkeypatch,
) -> None:
    async def migration_state(_engine):
        return {
            "current_revision": "20260609_0024",
            "head_revision": "20260609_0024",
            "is_current": True,
        }

    monkeypatch.setattr(health_routes, "get_migration_state", migration_state)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/runtime-info")

    assert response.status_code == 200
    migrations = response.json()["migrations"]
    assert set(migrations) == {"ok", "current_revision", "head_revision"}
    assert migrations["ok"] is True
    assert isinstance(migrations["current_revision"], str)
    assert isinstance(migrations["head_revision"], str)


@pytest.mark.asyncio
async def test_fresh_bootstrap_creates_core_workspace_without_default_teams(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "owner@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")

    await bootstrap.sync_default_workspace(db_session)

    assert await db_session.scalar(select(Organization)) is not None
    owner = await db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None
    assert await db_session.scalar(select(OrganizationSettings)) is not None
    assert list(await db_session.scalars(select(Provider))) != []
    assert list(await db_session.scalars(select(Team))) == []


@pytest.mark.asyncio
async def test_gateway_metadata_is_available_to_scoped_key_managers(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "owner@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        owner_headers = await _login(client, "owner@example.com", "correct-password")
        team = await client.post("/api/v1/teams", headers=owner_headers, json={"name": "Team A"})
        project = await client.post(
            f"/api/v1/teams/{team.json()['id']}/projects",
            headers=owner_headers,
            json={"name": "Project A"},
        )
        project_admin = await client.post(
            "/api/v1/auth/members",
            headers=owner_headers,
            json={
                "email": "project-admin@example.com",
                "password": "project-admin-password",
                "role": "org_member",
            },
        )
        await client.post(
            f"/api/v1/projects/{project.json()['id']}/members",
            headers=owner_headers,
            json={"user_id": project_admin.json()["user_id"], "role": "project_admin"},
        )
        await client.patch(
            "/api/v1/settings",
            headers=owner_headers,
            json={
                "public_base_url": "https://gateway.example.com",
                "virtual_key_prefix": "example",
                "default_virtual_key_expiration_days": 90,
            },
        )
        project_admin_headers = await _login(
            client,
            "project-admin@example.com",
            "project-admin-password",
        )

        settings_response = await client.get("/api/v1/settings", headers=project_admin_headers)
        metadata_response = await client.get(
            "/api/v1/settings/gateway-metadata",
            headers=project_admin_headers,
        )

    assert settings_response.status_code == 403
    assert metadata_response.status_code == 200
    assert metadata_response.json() == {
        "public_base_url": "https://gateway.example.com",
        "virtual_key_prefix": "example",
        "default_virtual_key_expiration_days": 90,
    }


@pytest.mark.asyncio
async def test_project_viewers_can_read_members_but_cannot_manage_them(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "owner@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        owner_headers = await _login(client, "owner@example.com", "correct-password")
        team = await client.post("/api/v1/teams", headers=owner_headers, json={"name": "Team A"})
        project = await client.post(
            f"/api/v1/teams/{team.json()['id']}/projects",
            headers=owner_headers,
            json={"name": "Project A"},
        )
        team_member = await client.post(
            "/api/v1/auth/members",
            headers=owner_headers,
            json={
                "email": "team-member@example.com",
                "password": "team-member-password",
                "role": "org_member",
            },
        )
        await client.post(
            f"/api/v1/teams/{team.json()['id']}/members",
            headers=owner_headers,
            json={"user_id": team_member.json()["user_id"], "role": "team_member"},
        )
        team_member_headers = await _login(
            client,
            "team-member@example.com",
            "team-member-password",
        )

        list_response = await client.get(
            f"/api/v1/projects/{project.json()['id']}/members",
            headers=team_member_headers,
        )
        add_response = await client.post(
            f"/api/v1/projects/{project.json()['id']}/members",
            headers=team_member_headers,
            json={"user_id": team_member.json()["user_id"], "role": "project_admin"},
        )

    assert list_response.status_code == 200
    assert list_response.json() == []
    assert add_response.status_code == 403


@pytest.mark.asyncio
async def test_scoped_users_cannot_list_or_fetch_out_of_scope_teams_and_projects(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "owner@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        owner_headers = await _login(client, "owner@example.com", "correct-password")
        team_a = await client.post("/api/v1/teams", headers=owner_headers, json={"name": "Team A"})
        team_b = await client.post("/api/v1/teams", headers=owner_headers, json={"name": "Team B"})
        project_a = await client.post(
            f"/api/v1/teams/{team_a.json()['id']}/projects",
            headers=owner_headers,
            json={"name": "Project A1"},
        )
        project_b = await client.post(
            f"/api/v1/teams/{team_b.json()['id']}/projects",
            headers=owner_headers,
            json={"name": "Project B1"},
        )
        team_admin = await client.post(
            "/api/v1/auth/members",
            headers=owner_headers,
            json={
                "email": "team-admin@example.com",
                "password": "team-admin-password",
                "role": "org_member",
            },
        )
        project_admin = await client.post(
            "/api/v1/auth/members",
            headers=owner_headers,
            json={
                "email": "project-admin@example.com",
                "password": "project-admin-password",
                "role": "org_member",
            },
        )
        await client.post(
            f"/api/v1/teams/{team_a.json()['id']}/members",
            headers=owner_headers,
            json={"user_id": team_admin.json()["user_id"], "role": "team_admin"},
        )
        await client.post(
            f"/api/v1/projects/{project_a.json()['id']}/members",
            headers=owner_headers,
            json={"user_id": project_admin.json()["user_id"], "role": "project_admin"},
        )

        team_admin_headers = await _login(
            client, "team-admin@example.com", "team-admin-password"
        )
        project_admin_headers = await _login(
            client, "project-admin@example.com", "project-admin-password"
        )
        team_admin_teams = await client.get("/api/v1/teams", headers=team_admin_headers)
        team_admin_projects = await client.get("/api/v1/projects", headers=team_admin_headers)
        team_admin_other_team = await client.get(
            f"/api/v1/teams/{team_b.json()['id']}", headers=team_admin_headers
        )
        team_admin_other_project = await client.get(
            f"/api/v1/projects/{project_b.json()['id']}", headers=team_admin_headers
        )
        project_admin_projects = await client.get(
            "/api/v1/projects", headers=project_admin_headers
        )
        project_admin_other_project = await client.get(
            f"/api/v1/projects/{project_b.json()['id']}", headers=project_admin_headers
        )
        project_admin_team_patch = await client.patch(
            f"/api/v1/teams/{team_a.json()['id']}",
            headers=project_admin_headers,
            json={"description": "blocked"},
        )

    assert team_admin_teams.status_code == 200
    assert [team["name"] for team in team_admin_teams.json()] == ["Team A"]
    assert team_admin_projects.status_code == 200
    assert [project["name"] for project in team_admin_projects.json()] == ["Project A1"]
    assert team_admin_other_team.status_code == 403
    assert team_admin_other_project.status_code == 403
    assert project_admin_projects.status_code == 200
    assert [project["name"] for project in project_admin_projects.json()] == ["Project A1"]
    assert project_admin_other_project.status_code == 403
    assert project_admin_team_patch.status_code == 403
