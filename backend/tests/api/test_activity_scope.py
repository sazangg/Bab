from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.database import Scope
from app.modules.activity.internal.models import ActivityEvent
from app.modules.auth.schemas import (
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
)
from app.modules.keys.internal.models import VirtualKey
from app.modules.policies import facade as policies_facade
from app.modules.policies.schemas import CreateAccessPolicyRequest, CreatePolicyAssignmentRequest
from app.modules.workspace.internal.models import Organization, Project, Team


def _principal(
    *,
    org_id: UUID,
    permissions: list[str] | None = None,
    team_memberships: list[AuthenticatedTeamMembership] | None = None,
    project_memberships: list[AuthenticatedProjectMembership] | None = None,
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        org_id=org_id,
        email=f"{uuid4()}@example.com",
        role="org_member",
        permissions=permissions or [],
        team_memberships=team_memberships or [],
        project_memberships=project_memberships or [],
    )


async def _workspace(db_session: AsyncSession):
    org = Organization(name=f"Activity {uuid4()}", slug=f"activity-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug="platform")
    other_team = Team(org_id=org.id, name="Other", slug="other")
    db_session.add_all([team, other_team])
    await db_session.flush()
    project = Project(
        org_id=org.id,
        team_id=team.id,
        created_by=uuid4(),
        name="Console",
        slug="console",
    )
    other_project = Project(
        org_id=org.id,
        team_id=other_team.id,
        created_by=uuid4(),
        name="Worker",
        slug="worker",
    )
    db_session.add_all([project, other_project])
    await db_session.flush()
    key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Console key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab-test",
    )
    other_key = VirtualKey(
        org_id=org.id,
        project_id=other_project.id,
        name="Worker key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab-test",
    )
    db_session.add_all([key, other_key])
    await db_session.flush()
    db_session.add_all(
        [
            _activity(
                org.id,
                team_id=team.id,
                project_id=project.id,
                virtual_key_id=key.id,
                message="allowed workspace event",
            ),
            _activity(
                org.id,
                team_id=other_team.id,
                project_id=other_project.id,
                virtual_key_id=other_key.id,
                message="blocked workspace event",
            ),
        ]
    )
    await db_session.commit()
    return org, team, project, other_team, other_project, key, other_key


async def _get(app_client, user: AuthenticatedUser, path: str):
    async def override_current_user():
        return user

    app_client.dependency_overrides[get_current_user] = override_current_user
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://test",
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_activity_viewer_can_see_org_activity(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, *_ = await _workspace(db_session)

    response = await _get(
        app_client,
        _principal(org_id=org.id, permissions=["activity.view"]),
        "/api/v1/activity",
    )

    assert response.status_code == 200
    assert {item["message"] for item in response.json()["items"]} == {
        "allowed workspace event",
        "blocked workspace event",
    }


@pytest.mark.asyncio
async def test_team_member_activity_is_limited_to_direct_team(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, project, other_team, *_ = await _workspace(db_session)
    db_session.add(
        _activity(org.id, project_id=project.id, message="allowed project-only event")
    )
    await db_session.commit()
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    response = await _get(app_client, user, "/api/v1/activity")
    assert response.status_code == 200
    assert {item["message"] for item in response.json()["items"]} == {
        "allowed workspace event",
        "allowed project-only event",
    }

    blocked = await _get(app_client, user, f"/api/v1/activity?team_id={other_team.id}")
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_project_admin_activity_is_limited_to_direct_project(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, _team, project, _other_team, other_project, key, *_ = await _workspace(db_session)
    db_session.add(
        _activity(org.id, virtual_key_id=key.id, message="allowed key-only event")
    )
    await db_session.commit()
    user = _principal(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    response = await _get(app_client, user, "/api/v1/activity")
    assert response.status_code == 200
    assert {item["message"] for item in response.json()["items"]} == {
        "allowed workspace event",
        "allowed key-only event",
    }

    blocked = await _get(app_client, user, f"/api/v1/activity?project_id={other_project.id}")
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_activity_scope_validates_project_team_and_virtual_key_filters(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, project, _other_team, other_project, key, other_key = await _workspace(db_session)
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    ok = await _get(
        app_client,
        user,
        f"/api/v1/activity?team_id={team.id}&virtual_key_id={key.id}",
    )
    assert ok.status_code == 200

    mismatched_project = await _get(
        app_client,
        user,
        f"/api/v1/activity?team_id={team.id}&project_id={other_project.id}",
    )
    assert mismatched_project.status_code == 403

    mismatched_key = await _get(
        app_client,
        user,
        f"/api/v1/activity?project_id={project.id}&virtual_key_id={other_key.id}",
    )
    assert mismatched_key.status_code == 403


@pytest.mark.asyncio
async def test_activity_entity_filters_cannot_bypass_scope(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, _project, _other_team, other_project, _key, other_key = await _workspace(db_session)
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    blocked_project = await _get(
        app_client,
        user,
        f"/api/v1/activity?entity_type=project&entity_id={other_project.id}",
    )
    assert blocked_project.status_code == 403

    blocked_key = await _get(
        app_client,
        user,
        f"/api/v1/activity?entity_type=virtual_key&entity_id={other_key.id}",
    )
    assert blocked_key.status_code == 403


@pytest.mark.asyncio
async def test_activity_date_filters_and_export_use_scope(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, _project, _other_team, *_ = await _workspace(db_session)
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat().replace("+00:00", "Z")

    empty = await _get(app_client, user, f"/api/v1/activity?start_at={future}")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["has_more"] is False
    assert empty.json()["next_before_at"] is None
    assert empty.json()["next_before_id"] is None

    exported = await _get(app_client, user, "/api/v1/activity/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "allowed workspace event" in exported.text
    assert "blocked workspace event" not in exported.text


@pytest.mark.asyncio
async def test_activity_search_cursor_and_export_share_filters(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, project, _other_team, *_ = await _workspace(db_session)
    first = _activity(
        org.id,
        team_id=team.id,
        project_id=project.id,
        message="matching older event",
    )
    first.actor_email = "operator@example.com"
    first.request_id = "req-search-older"
    first.metadata_ = {"reason": "quota_exceeded"}
    first.created_at = datetime.now(UTC) - timedelta(minutes=2)
    second = _activity(
        org.id,
        team_id=team.id,
        project_id=project.id,
        message="matching newer event",
    )
    second.actor_email = "operator@example.com"
    second.request_id = "req-search-newer"
    second.metadata_ = {"reason": "quota_exceeded"}
    second.created_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.add_all([first, second])
    await db_session.commit()
    user = _principal(org_id=org.id, permissions=["activity.view"])

    first_page = await _get(
        app_client,
        user,
        "/api/v1/activity?q=quota_exceeded&limit=1",
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    [newer] = first_body["items"]
    assert newer["message"] == "matching newer event"
    assert first_body["limit"] == 1
    assert first_body["has_more"] is True
    assert first_body["next_before_at"] == newer["created_at"]
    assert first_body["next_before_id"] == newer["id"]

    second_page = await _get(
        app_client,
        user,
        (
            "/api/v1/activity?q=quota_exceeded&limit=1"
            f"&before_at={newer['created_at']}&before_id={newer['id']}"
        ),
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert [item["message"] for item in second_body["items"]] == ["matching older event"]
    assert second_body["has_more"] is False
    assert second_body["next_before_at"] is None
    assert second_body["next_before_id"] is None

    exported = await _get(app_client, user, "/api/v1/activity/export?q=req-search")
    assert exported.status_code == 200
    assert "matching older event" in exported.text
    assert "matching newer event" in exported.text
    assert "allowed workspace event" not in exported.text


@pytest.mark.asyncio
async def test_activity_invalid_limit_returns_problem_detail(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, *_ = await _workspace(db_session)
    user = _principal(org_id=org.id, permissions=["activity.view"])

    response = await _get(app_client, user, "/api/v1/activity?limit=0")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 422


@pytest.mark.asyncio
async def test_team_scoped_users_see_only_team_policy_assignment_activity(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, _project, other_team, *_ = await _workspace(db_session)
    await _create_policy_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="team",
        team_id=team.id,
    )
    await _create_policy_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="team",
        team_id=other_team.id,
    )

    for role in ("team_member", "team_admin"):
        user = _principal(
            org_id=org.id,
            team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role=role)],
        )

        response = await _get(app_client, user, "/api/v1/activity?category=policy")

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["action"] for item in items] == ["policy_assignment.created"]
        assert items[0]["team_id"] == str(team.id)


@pytest.mark.asyncio
async def test_project_admin_sees_only_project_policy_assignment_activity(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, _team, project, _other_team, other_project, *_ = await _workspace(db_session)
    await _create_policy_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=project.id,
    )
    await _create_policy_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=other_project.id,
    )
    user = _principal(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    response = await _get(app_client, user, "/api/v1/activity?category=policy")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["action"] for item in items] == ["policy_assignment.created"]
    assert items[0]["project_id"] == str(project.id)


@pytest.mark.asyncio
async def test_virtual_key_policy_assignment_activity_includes_parent_context(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, project, _other_team, _other_project, key, *_ = await _workspace(db_session)
    await _create_policy_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="virtual_key",
        virtual_key_id=key.id,
    )
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    response = await _get(app_client, user, "/api/v1/activity?category=policy")

    assert response.status_code == 200
    [event] = response.json()["items"]
    assert event["action"] == "policy_assignment.created"
    assert event["team_id"] == str(team.id)
    assert event["project_id"] == str(project.id)
    assert event["virtual_key_id"] == str(key.id)


@pytest.mark.asyncio
async def test_scoped_users_do_not_see_org_policy_definition_activity(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, *_ = await _workspace(db_session)
    await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(name=f"Org policy {uuid4()}"),
        actor=_admin(org.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    response = await _get(app_client, user, "/api/v1/activity?category=policy")

    assert response.status_code == 200
    assert response.json()["items"] == []


def _activity(
    org_id: UUID,
    *,
    message: str,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
) -> ActivityEvent:
    return ActivityEvent(
        org_id=org_id,
        category="proxy",
        severity="warning",
        action="proxy.denied",
        message=message,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        metadata_={},
    )


def _admin(org_id: UUID) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        org_id=org_id,
        email="admin@example.com",
        role="org_admin",
        permissions=["*"],
    )


async def _create_policy_assignment(
    *,
    db_session: AsyncSession,
    org_id: UUID,
    scope_type: str,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
) -> None:
    policy = await policies_facade.create_access_policy(
        payload=CreateAccessPolicyRequest(name=f"Policy {uuid4()}"),
        actor=_admin(org_id),
        scope=Scope(org_id=org_id),
        db=db_session,
    )
    await policies_facade.create_policy_assignment(
        payload=CreatePolicyAssignmentRequest(
            policy_type="access",
            policy_id=policy.policy_id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        ),
        actor=_admin(org_id),
        scope=Scope(org_id=org_id),
        db=db_session,
    )

