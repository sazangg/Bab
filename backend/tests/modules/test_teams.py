from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.activity.internal.models import ActivityEvent
from app.modules.auth.internal.models import AuditEvent, Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as projects_facade
from app.modules.keys.errors import ProjectSlugAlreadyExistsError
from app.modules.keys.schemas import CreateProjectRequest, UpdateProjectRequest
from app.modules.teams import facade as teams_facade
from app.modules.teams.errors import TeamInactiveError, TeamSlugAlreadyExistsError
from app.modules.teams.schemas import CreateTeamRequest, UpdateTeamRequest


async def _create_actor_scope(db_session: AsyncSession):
    org = Organization(name=f"Teams {uuid4()}", slug=f"teams-{uuid4()}")
    db_session.add(org)
    await db_session.commit()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    return actor, Scope(org_id=org.id)


async def test_team_crud_flow(db_session: AsyncSession) -> None:
    actor, scope = await _create_actor_scope(db_session)

    team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Mobile Division", description="Native apps"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    updated = await teams_facade.update_team(
        team_id=team.id,
        payload=UpdateTeamRequest(name="Mobile Platform", description=None),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    teams = await teams_facade.list_teams(scope=scope, db=db_session)
    await teams_facade.deactivate_team(
        team_id=team.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )
    deactivated = await teams_facade.get_team(team_id=team.id, scope=scope, db=db_session)

    assert team.slug == "mobile-division"
    assert updated.name == "Mobile Platform"
    assert updated.description is None
    assert [item.id for item in teams] == [team.id]
    assert not deactivated.is_active


async def test_team_slug_is_unique_per_org(db_session: AsyncSession) -> None:
    actor, scope = await _create_actor_scope(db_session)
    await teams_facade.create_team(
        payload=CreateTeamRequest(name="Platform", slug="platform"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(TeamSlugAlreadyExistsError):
        await teams_facade.create_team(
            payload=CreateTeamRequest(name="Other", slug="platform"),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_team_slug_is_normalized_before_uniqueness_check(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    first = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Platform", slug="Data Platform!!"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(TeamSlugAlreadyExistsError):
        await teams_facade.create_team(
            payload=CreateTeamRequest(name="Other", slug="data-platform"),
            actor=actor,
            scope=scope,
            db=db_session,
        )

    assert first.slug == "data-platform"


async def test_projects_are_created_under_a_team(db_session: AsyncSession) -> None:
    actor, scope = await _create_actor_scope(db_session)
    team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Data Platform"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    project = await projects_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Embeddings API"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    projects = await projects_facade.list_team_projects(
        team_id=team.id,
        scope=scope,
        db=db_session,
    )

    assert project.team_id == team.id
    assert project.slug == "embeddings-api"
    assert [item.id for item in projects] == [project.id]


async def test_project_slug_is_normalized_and_unique_within_team(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Applications"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    other_team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Other Applications"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    first = await projects_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Console", slug="Admin Console!!"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    same_slug_other_team = await projects_facade.create_project(
        team_id=other_team.id,
        payload=CreateProjectRequest(name="Console", slug="admin-console"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(ProjectSlugAlreadyExistsError):
        await projects_facade.create_project(
            team_id=team.id,
            payload=CreateProjectRequest(name="Duplicate", slug="admin-console"),
            actor=actor,
            scope=scope,
            db=db_session,
        )

    assert first.slug == "admin-console"
    assert same_slug_other_team.slug == "admin-console"


async def test_project_slug_can_be_updated_when_unique(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Applications"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    project = await projects_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Console"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await projects_facade.create_project(
        team_id=team.id,
        payload=CreateProjectRequest(name="Worker", slug="worker"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    updated = await projects_facade.update_project(
        project_id=project.id,
        payload=UpdateProjectRequest(slug="Admin Console"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    with pytest.raises(ProjectSlugAlreadyExistsError):
        await projects_facade.update_project(
            project_id=project.id,
            payload=UpdateProjectRequest(slug="worker"),
            actor=actor,
            scope=scope,
            db=db_session,
        )

    assert updated.slug == "admin-console"


async def test_project_cannot_be_created_under_archived_team(db_session: AsyncSession) -> None:
    actor, scope = await _create_actor_scope(db_session)
    team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Archived Team"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await teams_facade.deactivate_team(
        team_id=team.id,
        actor=actor,
        scope=scope,
        db=db_session,
    )

    with pytest.raises(TeamInactiveError):
        await projects_facade.create_project(
            team_id=team.id,
            payload=CreateProjectRequest(name="Blocked Project"),
            actor=actor,
            scope=scope,
            db=db_session,
        )


async def test_team_archive_and_reactivation_events_include_resource_ids(
    db_session: AsyncSession,
) -> None:
    actor, scope = await _create_actor_scope(db_session)
    team = await teams_facade.create_team(
        payload=CreateTeamRequest(name="Lifecycle Team"),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    await teams_facade.update_team(
        team_id=team.id,
        payload=UpdateTeamRequest(is_active=False),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await teams_facade.update_team(
        team_id=team.id,
        payload=UpdateTeamRequest(is_active=True),
        actor=actor,
        scope=scope,
        db=db_session,
    )

    activity_events = list(
        await db_session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.team_id == team.id)
            .where(ActivityEvent.action.in_(["team.deactivated", "team.reactivated"]))
            .order_by(ActivityEvent.created_at)
        )
    )
    audit_events = list(
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == team.id)
            .where(AuditEvent.action.in_(["team.deactivated", "team.reactivated"]))
            .order_by(AuditEvent.created_at)
        )
    )

    assert [event.action for event in activity_events] == [
        "team.deactivated",
        "team.reactivated",
    ]
    assert [event.action for event in audit_events] == [
        "team.deactivated",
        "team.reactivated",
    ]
    assert {event.entity_type for event in audit_events} == {"team"}
    assert all(event.org_id == scope.org_id for event in activity_events + audit_events)
    assert all(event.metadata_["team_id"] == str(team.id) for event in activity_events)
