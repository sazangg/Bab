from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.keys import facade as projects_facade
from app.modules.keys.schemas import CreateProjectRequest
from app.modules.teams import facade as teams_facade
from app.modules.teams.errors import TeamSlugAlreadyExistsError
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
    assert [item.id for item in projects] == [project.id]
