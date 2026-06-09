from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.database import Scope
from app.modules.activity.internal.models import ActivityEvent
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import (
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
)
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.policies import facade as policies_facade
from app.modules.policies.schemas import CreateAccessPolicyRequest, CreatePolicyAssignmentRequest


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
    assert {item["message"] for item in response.json()} == {
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
    assert {item["message"] for item in response.json()} == {
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
    assert {item["message"] for item in response.json()} == {
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
    assert empty.json() == []

    exported = await _get(app_client, user, "/api/v1/activity/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "allowed workspace event" in exported.text
    assert "blocked workspace event" not in exported.text


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
        assert [item["action"] for item in response.json()] == ["policy_assignment.created"]
        assert response.json()[0]["team_id"] == str(team.id)


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
    assert [item["action"] for item in response.json()] == ["policy_assignment.created"]
    assert response.json()[0]["project_id"] == str(project.id)


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
    [event] = response.json()
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
    assert response.json() == []


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
            access_policy_id=policy.id,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
        ),
        actor=_admin(org_id),
        scope=Scope(org_id=org_id),
        db=db_session,
    )
