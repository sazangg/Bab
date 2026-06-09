from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.modules.activity.internal.models import ActivityEvent
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import (
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
)
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.usage.internal.models import UsageRecord


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
    org = Organization(name=f"Usage {uuid4()}", slug=f"usage-{uuid4()}")
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
    provider_id = uuid4()
    db_session.add_all(
        [
            _usage(org.id, team.id, project.id, key.id, provider_id, "gpt-5-mini", 10),
            _usage(
                org.id,
                other_team.id,
                other_project.id,
                other_key.id,
                provider_id,
                "gpt-5-mini",
                30,
            ),
        ]
    )
    await db_session.commit()
    return org, team, project, other_team, other_project, key, other_key, provider_id


def _usage(
    org_id: UUID,
    team_id: UUID,
    project_id: UUID,
    virtual_key_id: UUID,
    provider_id: UUID,
    model: str,
    total_tokens: int,
) -> UsageRecord:
    return UsageRecord(
        org_id=org_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        pool_id=uuid4(),
        provider_id=provider_id,
        provider_credential_id=None,
        requested_model=model,
        provider_model=model,
        http_status=200,
        latency_ms=100,
        prompt_tokens=total_tokens,
        completion_tokens=0,
        total_tokens=total_tokens,
        cost_cents=total_tokens,
        usage_source="estimated",
    )


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
async def test_usage_viewer_can_see_org_usage(app_client, db_session: AsyncSession) -> None:
    org, *_ = await _workspace(db_session)
    response = await _get(
        app_client,
        _principal(org_id=org.id, permissions=["usage.view"]),
        "/api/v1/usage/summary",
    )

    assert response.status_code == 200
    assert response.json()["totals"]["total_tokens"] == 40


@pytest.mark.asyncio
async def test_team_member_usage_is_limited_to_member_team(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, _project, other_team, *_ = await _workspace(db_session)
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    response = await _get(app_client, user, "/api/v1/usage/summary")
    assert response.status_code == 200
    assert response.json()["totals"]["total_tokens"] == 10

    blocked = await _get(app_client, user, f"/api/v1/usage/summary?team_id={other_team.id}")
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_team_admin_usage_is_limited_to_admin_team(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, _project, _other_team, _other_project, _key, _other_key, provider_id = (
        await _workspace(db_session)
    )
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )

    response = await _get(
        app_client,
        user,
        f"/api/v1/usage/records?provider_id={provider_id}",
    )

    assert response.status_code == 200
    assert [item["total_tokens"] for item in response.json()] == [10]


@pytest.mark.asyncio
async def test_project_admin_usage_is_limited_to_direct_project(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, _team, project, _other_team, other_project, *_ = await _workspace(db_session)
    user = _principal(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    response = await _get(app_client, user, "/api/v1/usage/timeseries")
    assert response.status_code == 200
    assert sum(item["total_tokens"] for item in response.json()) == 10

    blocked = await _get(
        app_client,
        user,
        f"/api/v1/usage/timeseries?project_id={other_project.id}",
    )
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_usage_scope_validates_project_team_and_virtual_key_filters(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, project, other_team, other_project, key, other_key, _provider_id = (
        await _workspace(db_session)
    )
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    ok = await _get(
        app_client,
        user,
        f"/api/v1/usage/spend-insights?team_id={team.id}&virtual_key_id={key.id}",
    )
    assert ok.status_code == 200

    mismatched_project = await _get(
        app_client,
        user,
        f"/api/v1/usage/records/export?team_id={team.id}&project_id={other_project.id}",
    )
    assert mismatched_project.status_code == 403

    mismatched_key = await _get(
        app_client,
        user,
        f"/api/v1/usage/records?project_id={project.id}&virtual_key_id={other_key.id}",
    )
    assert mismatched_key.status_code == 403

    out_of_scope_team = await _get(
        app_client,
        user,
        f"/api/v1/usage/summary?team_id={other_team.id}",
    )
    assert out_of_scope_team.status_code == 403


@pytest.mark.asyncio
async def test_user_without_usage_scope_is_forbidden(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, *_ = await _workspace(db_session)

    response = await _get(app_client, _principal(org_id=org.id), "/api/v1/usage/summary")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_team_member_summary_recent_denials_are_scoped(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, team, _project, other_team, *_ = await _workspace(db_session)
    db_session.add_all(
        [
            _activity(org.id, team_id=team.id, message="allowed team denial"),
            _activity(org.id, team_id=other_team.id, message="blocked team denial"),
        ]
    )
    await db_session.commit()
    user = _principal(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_member")],
    )

    response = await _get(app_client, user, "/api/v1/usage/summary")

    assert response.status_code == 200
    messages = [event["message"] for event in response.json()["recent_denials"]]
    assert messages == ["allowed team denial"]


@pytest.mark.asyncio
async def test_project_admin_summary_recent_denials_are_scoped_to_direct_projects(
    app_client,
    db_session: AsyncSession,
) -> None:
    org, _team, project, _other_team, other_project, *_ = await _workspace(db_session)
    db_session.add_all(
        [
            _activity(org.id, project_id=project.id, message="allowed project denial"),
            _activity(org.id, project_id=other_project.id, message="blocked project denial"),
        ]
    )
    await db_session.commit()
    user = _principal(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    response = await _get(app_client, user, "/api/v1/usage/summary")

    assert response.status_code == 200
    messages = [event["message"] for event in response.json()["recent_denials"]]
    assert messages == ["allowed project denial"]


def _activity(
    org_id: UUID,
    *,
    message: str,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
) -> ActivityEvent:
    return ActivityEvent(
        org_id=org_id,
        category="proxy",
        severity="warning",
        action="proxy.denied",
        message=message,
        team_id=team_id,
        project_id=project_id,
        metadata_={},
    )
