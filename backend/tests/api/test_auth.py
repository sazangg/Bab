from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import bootstrap
from app.core.security import decode_access_token, hash_token
from app.modules.audit.internal.models import AuditEvent
from app.modules.auth.internal.models import (
    Invite,
    OrganizationMembership,
    ProjectMembership,
    RefreshSession,
    TeamMembership,
    User,
)
from app.modules.workspace.internal.models import Team


def _parse_api_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
    refresh_session = await db_session.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_token(cookie["bab_refresh_token"].value)
        )
    )
    assert refresh_session is not None
    assert refresh_session.user_id == bootstrap.DEFAULT_ADMIN_USER_ID
    assert refresh_session.revoked_at is None


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

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        replay_response = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"bab_refresh_token={first_cookie}"},
        )

    assert response.status_code == 200
    assert first_cookie
    assert second_cookie
    assert second_cookie != first_cookie
    assert replay_response.status_code == 401
    old_session = await db_session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(first_cookie))
    )
    new_session = await db_session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(second_cookie))
    )
    assert old_session is not None
    assert new_session is not None
    assert old_session.revoked_at is not None
    assert old_session.replaced_by_session_id == new_session.id
    # Replaying the already-rotated token is treated as reuse: the whole rotation
    # family (including the live successor) is revoked, forcing re-authentication.
    assert new_session.revoked_at is not None


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
        refresh_cookie = client.cookies["bab_refresh_token"]
        response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert "bab_refresh_token" not in client.cookies
    refresh_session = await db_session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_cookie))
    )
    audit_event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "refresh_session.revoked")
    )
    assert refresh_session is not None
    assert refresh_session.revoked_at is not None
    assert audit_event is not None
    assert audit_event.metadata_["reason"] == "logout"
    assert audit_event.metadata_["user_id"] == str(refresh_session.user_id)
    assert "token" not in audit_event.metadata_
    assert "token_hash" not in audit_event.metadata_


@pytest.mark.asyncio
async def test_bootstrap_does_not_create_default_team_or_membership(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")

    await bootstrap.sync_default_workspace(db_session)

    teams = list(await db_session.scalars(select(Team)))
    team_memberships = list(await db_session.scalars(select(TeamMembership)))
    admin_membership = await db_session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == bootstrap.DEFAULT_ADMIN_USER_ID
        )
    )
    assert teams == []
    assert team_memberships == []
    assert admin_membership is not None
    assert admin_membership.role == "org_owner"


@pytest.mark.asyncio
async def test_refresh_rejects_expired_token(
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
        refresh_cookie = client.cookies["bab_refresh_token"]
        refresh_session = await db_session.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_cookie))
        )
        assert refresh_session is not None
        refresh_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
        response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_revoked_token(
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
        refresh_cookie = client.cookies["bab_refresh_token"]
        await client.post("/api/v1/auth/logout")
        response = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"bab_refresh_token={refresh_cookie}"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_inactive_user_or_membership(
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
        user_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
        )
        user_cookie = client.cookies["bab_refresh_token"]
        admin_headers = {"Authorization": f"Bearer {user_response.json()['access_token']}"}
        create_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "member-refresh@example.com",
                "password": "member-password",
                "role": "org_member",
            },
            headers=admin_headers,
        )
        member_login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "member-refresh@example.com", "password": "member-password"},
        )
        membership_cookie = client.cookies["bab_refresh_token"]

        user = await db_session.scalar(
            select(User).where(User.id == bootstrap.DEFAULT_ADMIN_USER_ID)
        )
        assert user is not None
        user.is_active = False
        membership = await db_session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == UUID(create_response.json()["user_id"])
            )
        )
        assert membership is not None
        membership.status = "inactive"
        await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        inactive_user_response = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"bab_refresh_token={user_cookie}"},
        )
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        inactive_membership_response = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"bab_refresh_token={membership_cookie}"},
        )

    assert member_login_response.status_code == 200
    assert inactive_user_response.status_code == 401
    assert inactive_membership_response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_cookie_uses_secure_flag_in_production_config(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    monkeypatch.setattr(bootstrap.settings, "environment", "production")
    monkeypatch.setattr(bootstrap.settings, "refresh_cookie_secure", None)
    monkeypatch.setattr(bootstrap.settings, "refresh_cookie_samesite", "strict")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="https://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-password"},
        )

    cookie = SimpleCookie(response.headers["set-cookie"])
    assert response.status_code == 200
    assert cookie["bab_refresh_token"]["secure"]
    assert cookie["bab_refresh_token"]["samesite"] == "strict"


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
        missing_remove_response = await client.delete(
            f"/api/v1/teams/{team_response.json()['id']}/members/{member['user_id']}",
            headers=admin_headers,
        )
        audit_response = await client.get("/api/v1/audit", headers=admin_headers)
        audit_first_page_response = await client.get(
            "/api/v1/audit",
            params={"limit": 1},
            headers=admin_headers,
        )
        audit_first_page = audit_first_page_response.json()
        audit_second_page_response = await client.get(
            "/api/v1/audit",
            params={
                "limit": 1,
                "before_at": audit_first_page["next_before_at"],
                "before_id": audit_first_page["next_before_id"],
            },
            headers=admin_headers,
        )
        audit_invalid_limit_response = await client.get(
            "/api/v1/audit",
            params={"limit": 0},
            headers=admin_headers,
        )
        audit_export_response = await client.get(
            "/api/v1/audit/export",
            params={"action": "team_member.added"},
            headers=admin_headers,
        )
        audit_verify_response = await client.get("/api/v1/audit/verify", headers=admin_headers)

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
    assert missing_remove_response.status_code == 404
    assert audit_response.status_code == 200
    audit_actions = {event["action"] for event in audit_response.json()["items"]}
    assert {
        "invite.created",
        "team_member.added",
        "team_member.role_updated",
        "team_member.removed",
    }.issubset(audit_actions)
    assert audit_first_page_response.status_code == 200
    [latest_audit_event] = audit_first_page["items"]
    assert audit_first_page["limit"] == 1
    assert audit_first_page["has_more"] is True
    assert audit_first_page["next_before_at"] == latest_audit_event["created_at"]
    assert audit_first_page["next_before_id"] == latest_audit_event["id"]
    assert audit_second_page_response.status_code == 200
    audit_second_page = audit_second_page_response.json()
    assert len(audit_second_page["items"]) == 1
    assert audit_second_page["items"][0]["id"] != latest_audit_event["id"]
    assert audit_invalid_limit_response.status_code == 422
    assert audit_invalid_limit_response.headers["content-type"].startswith(
        "application/problem+json"
    )
    assert audit_export_response.status_code == 200
    assert audit_export_response.headers["content-type"].startswith("text/csv")
    assert "team_member.added" in audit_export_response.text
    assert "team_member.role_updated" not in audit_export_response.text
    assert "event_hash" in audit_export_response.text
    assert audit_verify_response.status_code == 200
    assert audit_verify_response.json()["valid"] is True, audit_verify_response.json()
    assert audit_verify_response.json()["checked_events"] >= 4


@pytest.mark.asyncio
async def test_invite_url_uses_origin_fallback_and_public_app_url(
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
        relative_response = await client.post(
            "/api/v1/auth/invites",
            headers={**admin_headers, "Origin": "http://127.0.0.1:5173"},
            json={"email": "relative-invite@example.com", "role": "org_member"},
        )
        settings_response = await client.patch(
            "/api/v1/settings",
            headers=admin_headers,
            json={"public_app_url": "https://app.example.com/"},
        )
        absolute_response = await client.post(
            "/api/v1/auth/invites",
            headers=admin_headers,
            json={"email": "absolute-invite@example.com", "role": "org_member"},
        )

    assert relative_response.status_code == 201
    assert relative_response.json()["invite_url"].startswith(
        "http://127.0.0.1:5173/accept-invite?token="
    )
    assert settings_response.status_code == 200
    assert settings_response.json()["public_app_url"] == "https://app.example.com"
    assert absolute_response.status_code == 201
    assert absolute_response.json()["invite_url"].startswith(
        "https://app.example.com/accept-invite?token="
    )


@pytest.mark.asyncio
async def test_project_invite_acceptance_creates_project_membership(
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
            json={"name": "Project Invite Team"},
            headers=admin_headers,
        )
        project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Project Invite"},
            headers=admin_headers,
        )
        invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "project-invite@example.com",
                "role": "org_member",
                "team_id": team_response.json()["id"],
                "team_role": "team_member",
                "project_id": project_response.json()["id"],
                "project_role": "project_admin",
            },
            headers=admin_headers,
        )
        invite_token = parse_qs(urlparse(invite_response.json()["invite_url"]).query)["token"][0]
        accept_response = await client.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": invite_token,
                "name": "Project Invite",
                "password": "project-invite-password",
            },
        )
        members_response = await client.get("/api/v1/auth/members", headers=admin_headers)
        missing_project_member_response = await client.delete(
            f"/api/v1/projects/{project_response.json()['id']}/members/{uuid4()}",
            headers=admin_headers,
        )

    member = next(
        item for item in members_response.json() if item["email"] == "project-invite@example.com"
    )
    project_membership = await db_session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == UUID(project_response.json()["id"]),
            ProjectMembership.user_id == UUID(member["user_id"]),
        )
    )
    assert invite_response.status_code == 201
    assert invite_response.json()["project_id"] == project_response.json()["id"]
    assert invite_response.json()["project_role"] == "project_admin"
    assert accept_response.status_code == 200
    assert missing_project_member_response.status_code == 404
    assert member["team_memberships"] == [
        {"team_id": team_response.json()["id"], "role": "team_member"}
    ]
    assert member["project_memberships"] == [
        {"project_id": project_response.json()["id"], "role": "project_admin"}
    ]
    assert "keys.manage" in member["effective_permissions"]
    assert project_membership is not None
    assert project_membership.role == "project_admin"


@pytest.mark.asyncio
async def test_invite_preview_exposes_safe_acceptance_context(
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
        team_response = await client.post(
            "/api/v1/teams",
            headers=headers,
            json={"name": "Preview Team"},
        )
        project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            headers=headers,
            json={"name": "Preview Project"},
        )
        invite_response = await client.post(
            "/api/v1/auth/invites",
            headers=headers,
            json={
                "email": "preview-invite@example.com",
                "role": "org_member",
                "team_id": team_response.json()["id"],
                "team_role": "team_member",
                "project_id": project_response.json()["id"],
                "project_role": "project_admin",
            },
        )
        invite_token = parse_qs(urlparse(invite_response.json()["invite_url"]).query)["token"][0]
        preview_response = await client.get(
            "/api/v1/auth/invites/preview",
            params={"token": invite_token},
        )

    assert preview_response.status_code == 200
    preview = preview_response.json()
    preview_expires_at = _parse_api_datetime(preview.pop("expires_at"))
    invite_expires_at = _parse_api_datetime(invite_response.json()["expires_at"])
    assert preview == {
        "email": "preview-invite@example.com",
        "organization_name": "Default Organization",
        "role": "org_member",
        "team_name": "Preview Team",
        "team_role": "team_member",
        "project_name": "Preview Project",
        "project_role": "project_admin",
        "status": "pending",
    }
    assert preview_expires_at == invite_expires_at


@pytest.mark.asyncio
async def test_invite_lifecycle_and_target_validation(
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
            json={"name": "Invite Validation A"},
            headers=admin_headers,
        )
        other_team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Invite Validation B"},
            headers=admin_headers,
        )
        project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Invite Validation Project"},
            headers=admin_headers,
        )
        team_role_without_team_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "bad-team@example.com", "team_role": "team_member"},
            headers=admin_headers,
        )
        project_without_role_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "bad-project@example.com",
                "project_id": project_response.json()["id"],
            },
            headers=admin_headers,
        )
        mismatched_project_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "bad-mismatch@example.com",
                "team_id": other_team_response.json()["id"],
                "team_role": "team_member",
                "project_id": project_response.json()["id"],
                "project_role": "project_admin",
            },
            headers=admin_headers,
        )
        duplicate_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "duplicate@example.com", "role": "org_member"},
            headers=admin_headers,
        )
        duplicate_again_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "duplicate@example.com", "role": "org_viewer"},
            headers=admin_headers,
        )
        accepted_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "accepted-once@example.com", "role": "org_member"},
            headers=admin_headers,
        )
        accepted_token = parse_qs(urlparse(accepted_invite_response.json()["invite_url"]).query)[
            "token"
        ][0]
        first_accept_response = await client.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": accepted_token,
                "name": "Accepted Once",
                "password": "accepted-password",
            },
        )
        second_accept_response = await client.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": accepted_token,
                "name": "Accepted Twice",
                "password": "accepted-password",
            },
        )
        revoked_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "revoked@example.com", "role": "org_member"},
            headers=admin_headers,
        )
        revoked_token = parse_qs(urlparse(revoked_invite_response.json()["invite_url"]).query)[
            "token"
        ][0]
        revoke_response = await client.delete(
            f"/api/v1/auth/invites/{revoked_invite_response.json()['id']}",
            headers=admin_headers,
        )
        missing_revoke_response = await client.delete(
            f"/api/v1/auth/invites/{uuid4()}",
            headers=admin_headers,
        )
        revoked_accept_response = await client.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": revoked_token,
                "name": "Revoked",
                "password": "revoked-password",
            },
        )
        expired_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "expired@example.com", "role": "org_member"},
            headers=admin_headers,
        )
        expired_token = parse_qs(urlparse(expired_invite_response.json()["invite_url"]).query)[
            "token"
        ][0]
        expired_invite = await db_session.scalar(
            select(Invite).where(Invite.id == UUID(expired_invite_response.json()["id"]))
        )
        assert expired_invite is not None
        expired_invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
        expired_accept_response = await client.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": expired_token,
                "name": "Expired",
                "password": "expired-password",
            },
        )
        expired_revoke_response = await client.delete(
            f"/api/v1/auth/invites/{expired_invite_response.json()['id']}",
            headers=admin_headers,
        )
        list_response = await client.get("/api/v1/auth/invites", headers=admin_headers)

    listed_expired = next(
        item for item in list_response.json() if item["email"] == "expired@example.com"
    )
    assert team_role_without_team_response.status_code == 400
    assert project_without_role_response.status_code == 400
    assert mismatched_project_response.status_code == 400
    assert duplicate_invite_response.status_code == 201
    assert duplicate_again_response.status_code == 409
    assert first_accept_response.status_code == 200
    assert second_accept_response.status_code == 400
    assert revoke_response.status_code == 204
    assert missing_revoke_response.status_code == 404
    assert revoked_accept_response.status_code == 400
    assert expired_accept_response.status_code == 400
    assert expired_revoke_response.status_code == 400
    assert listed_expired["status"] == "expired"


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
async def test_admin_can_create_local_user_with_initial_scoped_assignment(
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
            json={"name": "Initial Scope Team"},
            headers=admin_headers,
        )
        project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Initial Scope Project"},
            headers=admin_headers,
        )
        create_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "scoped-local@example.com",
                "password": "scoped-password",
                "role": "org_member",
                "team_id": team_response.json()["id"],
                "team_role": "team_member",
                "project_id": project_response.json()["id"],
                "project_role": "project_admin",
            },
            headers=admin_headers,
        )

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["team_memberships"] == [
        {"team_id": team_response.json()["id"], "role": "team_member"}
    ]
    assert body["project_memberships"] == [
        {"project_id": project_response.json()["id"], "role": "project_admin"}
    ]


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
        cross_scope_team_response = await client.get(
            f"/api/v1/teams/{other_team_response.json()['id']}",
            headers=team_admin_headers,
        )
        cross_scope_project_response = await client.get(
            f"/api/v1/projects/{other_project_response.json()['id']}",
            headers=team_admin_headers,
        )
        own_member_options_response = await client.get(
            f"/api/v1/teams/{team_response.json()['id']}/member-options",
            headers=team_admin_headers,
        )
        other_member_options_response = await client.get(
            f"/api/v1/teams/{other_team_response.json()['id']}/member-options",
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
    assert cross_scope_team_response.status_code == 403
    assert cross_scope_project_response.status_code == 403
    assert own_member_options_response.status_code == 200
    assert all(
        set(member) == {"user_id", "email", "name"} for member in own_member_options_response.json()
    )
    assert other_member_options_response.status_code == 403


@pytest.mark.asyncio
async def test_org_viewer_cannot_access_audit(
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
        owner_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct-password"},
        )
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        await client.post(
            "/api/v1/auth/members",
            json={
                "email": "viewer@example.com",
                "password": "viewer-password",
                "role": "org_viewer",
            },
            headers=owner_headers,
        )
        viewer_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "viewer-password"},
        )
        viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
        viewer_me_response = await client.get("/api/v1/auth/me", headers=viewer_headers)
        audit_response = await client.get("/api/v1/audit", headers=viewer_headers)

    assert viewer_login.status_code == 200
    assert "audit.view" not in viewer_me_response.json()["permissions"]
    assert audit_response.status_code == 403


@pytest.mark.asyncio
async def test_create_existing_member_does_not_reset_password(
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
        owner_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct-password"},
        )
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        first_create = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "member@example.com",
                "password": "original-password",
                "role": "org_member",
            },
            headers=owner_headers,
        )
        duplicate_create = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "member@example.com",
                "password": "replacement-password",
                "role": "org_admin",
            },
            headers=owner_headers,
        )
        original_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "member@example.com", "password": "original-password"},
        )
        replacement_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "member@example.com", "password": "replacement-password"},
        )

    assert first_create.status_code == 201
    assert duplicate_create.status_code == 409
    assert original_login.status_code == 200
    assert replacement_login.status_code == 401


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


@pytest.mark.asyncio
async def test_org_role_hierarchy_is_enforced(
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
        owner_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct-password"},
        )
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        admin_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "admin@example.com",
                "password": "admin-password",
                "role": "org_admin",
            },
            headers=owner_headers,
        )
        viewer_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "viewer-hierarchy@example.com",
                "password": "viewer-password",
                "role": "org_viewer",
            },
            headers=owner_headers,
        )
        owner_peer_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "owner-peer@example.com",
                "password": "owner-peer-password",
                "role": "org_owner",
            },
            headers=owner_headers,
        )
        admin_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-password"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
        admin_creates_member_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "member-hierarchy@example.com",
                "password": "member-password",
                "role": "org_member",
            },
            headers=admin_headers,
        )
        admin_creates_admin_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "blocked-admin@example.com",
                "password": "blocked-password",
                "role": "org_admin",
            },
            headers=admin_headers,
        )
        admin_promotes_viewer_response = await client.patch(
            f"/api/v1/auth/members/{viewer_response.json()['user_id']}",
            json={"role": "org_admin"},
            headers=admin_headers,
        )
        owner_promotes_viewer_response = await client.patch(
            f"/api/v1/auth/members/{viewer_response.json()['user_id']}",
            json={"role": "org_admin"},
            headers=owner_headers,
        )
        admin_demotes_admin_response = await client.patch(
            f"/api/v1/auth/members/{viewer_response.json()['user_id']}",
            json={"role": "org_member"},
            headers=admin_headers,
        )
        owner_self_deactivate_response = await client.patch(
            "/api/v1/auth/members/00000000-0000-4000-8000-000000000001/status",
            json={"status": "inactive"},
            headers=owner_headers,
        )

    assert admin_response.status_code == 201
    assert viewer_response.status_code == 201
    assert owner_peer_response.status_code == 201
    assert admin_creates_member_response.status_code == 201
    assert admin_creates_admin_response.status_code == 403
    assert admin_promotes_viewer_response.status_code == 403
    assert owner_promotes_viewer_response.status_code == 200
    assert admin_demotes_admin_response.status_code == 403
    assert owner_self_deactivate_response.status_code == 403


@pytest.mark.asyncio
async def test_scoped_membership_management_is_enforced(
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
        owner_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct-password"},
        )
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Scoped A"},
            headers=owner_headers,
        )
        other_team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Scoped B"},
            headers=owner_headers,
        )
        project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Project A"},
            headers=owner_headers,
        )
        other_project_response = await client.post(
            f"/api/v1/teams/{other_team_response.json()['id']}/projects",
            json={"name": "Project B"},
            headers=owner_headers,
        )
        team_admin_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "team-admin@example.com",
                "password": "team-admin-password",
                "role": "org_member",
            },
            headers=owner_headers,
        )
        project_admin_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "project-admin@example.com",
                "password": "project-admin-password",
                "role": "org_member",
            },
            headers=owner_headers,
        )
        target_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "target@example.com",
                "password": "target-password",
                "role": "org_member",
            },
            headers=owner_headers,
        )
        await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/members",
            json={"user_id": team_admin_response.json()["user_id"], "role": "team_admin"},
            headers=owner_headers,
        )
        await client.post(
            f"/api/v1/projects/{project_response.json()['id']}/members",
            json={"user_id": project_admin_response.json()["user_id"], "role": "project_admin"},
            headers=owner_headers,
        )

        team_admin_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "team-admin@example.com", "password": "team-admin-password"},
        )
        team_admin_headers = {"Authorization": f"Bearer {team_admin_login.json()['access_token']}"}
        team_admin_add_team_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/members",
            json={"user_id": target_response.json()["user_id"], "role": "team_member"},
            headers=team_admin_headers,
        )
        team_admin_other_team_response = await client.post(
            f"/api/v1/teams/{other_team_response.json()['id']}/members",
            json={"user_id": target_response.json()["user_id"], "role": "team_member"},
            headers=team_admin_headers,
        )
        team_admin_project_response = await client.post(
            f"/api/v1/projects/{project_response.json()['id']}/members",
            json={"user_id": target_response.json()["user_id"], "role": "project_admin"},
            headers=team_admin_headers,
        )
        team_admin_other_project_response = await client.post(
            f"/api/v1/projects/{other_project_response.json()['id']}/members",
            json={"user_id": target_response.json()["user_id"], "role": "project_admin"},
            headers=team_admin_headers,
        )

        project_admin_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "project-admin@example.com", "password": "project-admin-password"},
        )
        project_admin_headers = {
            "Authorization": f"Bearer {project_admin_login.json()['access_token']}"
        }
        project_admin_team_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/members",
            json={"user_id": target_response.json()["user_id"], "role": "team_member"},
            headers=project_admin_headers,
        )
        project_admin_project_response = await client.patch(
            f"/api/v1/projects/{project_response.json()['id']}/members/{target_response.json()['user_id']}",
            json={"role": "project_admin"},
            headers=project_admin_headers,
        )
        project_admin_other_project_response = await client.post(
            f"/api/v1/projects/{other_project_response.json()['id']}/members",
            json={"user_id": target_response.json()["user_id"], "role": "project_admin"},
            headers=project_admin_headers,
        )

    assert team_admin_add_team_response.status_code == 201
    assert team_admin_other_team_response.status_code == 403
    assert team_admin_project_response.status_code == 201
    assert team_admin_other_project_response.status_code == 403
    assert project_admin_team_response.status_code == 403
    assert project_admin_project_response.status_code == 200
    assert project_admin_other_project_response.status_code == 403


@pytest.mark.asyncio
async def test_scoped_invite_permissions_are_enforced(
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
        owner_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct-password"},
        )
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Invite Scope A"},
            headers=owner_headers,
        )
        other_team_response = await client.post(
            "/api/v1/teams",
            json={"name": "Invite Scope B"},
            headers=owner_headers,
        )
        project_response = await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/projects",
            json={"name": "Invite Project A"},
            headers=owner_headers,
        )
        other_project_response = await client.post(
            f"/api/v1/teams/{other_team_response.json()['id']}/projects",
            json={"name": "Invite Project B"},
            headers=owner_headers,
        )
        org_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={"email": "org-only-invite@example.com", "role": "org_member"},
            headers=owner_headers,
        )
        other_team_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "other-team-invite@example.com",
                "team_id": other_team_response.json()["id"],
                "team_role": "team_member",
            },
            headers=owner_headers,
        )
        team_admin_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "invite-team-admin@example.com",
                "password": "team-admin-password",
                "role": "org_member",
            },
            headers=owner_headers,
        )
        project_admin_response = await client.post(
            "/api/v1/auth/members",
            json={
                "email": "invite-project-admin@example.com",
                "password": "project-admin-password",
                "role": "org_member",
            },
            headers=owner_headers,
        )
        await client.post(
            f"/api/v1/teams/{team_response.json()['id']}/members",
            json={"user_id": team_admin_response.json()["user_id"], "role": "team_admin"},
            headers=owner_headers,
        )
        await client.post(
            f"/api/v1/projects/{project_response.json()['id']}/members",
            json={"user_id": project_admin_response.json()["user_id"], "role": "project_admin"},
            headers=owner_headers,
        )

        team_admin_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "invite-team-admin@example.com", "password": "team-admin-password"},
        )
        team_admin_headers = {"Authorization": f"Bearer {team_admin_login.json()['access_token']}"}
        team_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "team-invite@example.com",
                "team_id": team_response.json()["id"],
                "team_role": "team_member",
            },
            headers=team_admin_headers,
        )
        team_project_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "team-project-invite@example.com",
                "project_id": project_response.json()["id"],
                "project_role": "project_admin",
            },
            headers=team_admin_headers,
        )
        team_admin_org_admin_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "blocked-org-admin@example.com",
                "role": "org_admin",
                "team_id": team_response.json()["id"],
                "team_role": "team_member",
            },
            headers=team_admin_headers,
        )
        team_admin_other_project_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "blocked-other-project@example.com",
                "project_id": other_project_response.json()["id"],
                "project_role": "project_admin",
            },
            headers=team_admin_headers,
        )
        team_admin_list_response = await client.get(
            "/api/v1/auth/invites",
            headers=team_admin_headers,
        )
        team_admin_revoke_team_response = await client.delete(
            f"/api/v1/auth/invites/{team_invite_response.json()['id']}",
            headers=team_admin_headers,
        )
        team_admin_revoke_unrelated_response = await client.delete(
            f"/api/v1/auth/invites/{other_team_invite_response.json()['id']}",
            headers=team_admin_headers,
        )

        project_admin_login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "invite-project-admin@example.com",
                "password": "project-admin-password",
            },
        )
        project_admin_headers = {
            "Authorization": f"Bearer {project_admin_login.json()['access_token']}"
        }
        project_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "project-only-invite@example.com",
                "project_id": project_response.json()["id"],
                "project_role": "project_admin",
            },
            headers=project_admin_headers,
        )
        project_admin_team_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "blocked-team-invite@example.com",
                "team_id": team_response.json()["id"],
                "team_role": "team_member",
            },
            headers=project_admin_headers,
        )
        project_admin_other_project_invite_response = await client.post(
            "/api/v1/auth/invites",
            json={
                "email": "blocked-project-invite@example.com",
                "project_id": other_project_response.json()["id"],
                "project_role": "project_admin",
            },
            headers=project_admin_headers,
        )
        project_admin_list_response = await client.get(
            "/api/v1/auth/invites",
            headers=project_admin_headers,
        )
        project_admin_revoke_project_response = await client.delete(
            f"/api/v1/auth/invites/{project_invite_response.json()['id']}",
            headers=project_admin_headers,
        )
        project_admin_revoke_team_response = await client.delete(
            f"/api/v1/auth/invites/{team_project_invite_response.json()['id']}",
            headers=project_admin_headers,
        )
        owner_list_response = await client.get("/api/v1/auth/invites", headers=owner_headers)

    team_admin_invite_emails = {invite["email"] for invite in team_admin_list_response.json()}
    project_admin_invite_emails = {invite["email"] for invite in project_admin_list_response.json()}
    owner_invite_emails = {invite["email"] for invite in owner_list_response.json()}
    assert org_invite_response.status_code == 201
    assert other_team_invite_response.status_code == 201
    assert team_invite_response.status_code == 201
    assert team_invite_response.json()["role"] == "org_member"
    assert team_project_invite_response.status_code == 201
    assert team_admin_org_admin_invite_response.status_code == 403
    assert team_admin_other_project_invite_response.status_code == 403
    assert team_admin_list_response.status_code == 200
    assert "team-invite@example.com" in team_admin_invite_emails
    assert "team-project-invite@example.com" in team_admin_invite_emails
    assert "project-only-invite@example.com" not in team_admin_invite_emails
    assert "org-only-invite@example.com" not in team_admin_invite_emails
    assert "other-team-invite@example.com" not in team_admin_invite_emails
    assert team_admin_revoke_team_response.status_code == 204
    assert team_admin_revoke_unrelated_response.status_code == 403
    assert project_invite_response.status_code == 201
    assert project_admin_team_invite_response.status_code == 403
    assert project_admin_other_project_invite_response.status_code == 403
    assert project_admin_list_response.status_code == 200
    assert "project-only-invite@example.com" in project_admin_invite_emails
    assert "team-project-invite@example.com" in project_admin_invite_emails
    assert "team-invite@example.com" not in project_admin_invite_emails
    assert "org-only-invite@example.com" not in project_admin_invite_emails
    assert project_admin_revoke_project_response.status_code == 204
    assert project_admin_revoke_team_response.status_code == 204
    assert owner_list_response.status_code == 200
    assert "org-only-invite@example.com" in owner_invite_emails
    assert "other-team-invite@example.com" in owner_invite_emails
