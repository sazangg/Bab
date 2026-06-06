from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_project_view_or_permission, require_team_view_or_permission
from app.modules.auth.internal.models import (
    Organization,
    ProjectMembership,
    Team,
    TeamMembership,
    User,
)
from app.modules.auth.schemas import (
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
)
from app.modules.keys.internal.models import Project


def _user(
    *,
    org_id,
    role: str = "org_member",
    permissions: list[str] | None = None,
    team_memberships: list[AuthenticatedTeamMembership] | None = None,
    project_memberships: list[AuthenticatedProjectMembership] | None = None,
) -> AuthenticatedUser:
    user_id = uuid4()
    return AuthenticatedUser(
        id=user_id,
        org_id=org_id,
        email=f"{uuid4()}@example.com",
        role=role,
        permissions=permissions or [],
        team_memberships=team_memberships or [],
        project_memberships=project_memberships or [],
    )


def _user_row(user: AuthenticatedUser) -> User:
    return User(id=user.id, email=user.email)


async def _workspace(db_session: AsyncSession):
    org = Organization(name=f"Permissions {uuid4()}", slug=f"permissions-{uuid4()}")
    other_org = Organization(name=f"Other {uuid4()}", slug=f"other-{uuid4()}")
    db_session.add_all([org, other_org])
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug="platform")
    other_team = Team(org_id=org.id, name="Other", slug="other")
    cross_org_team = Team(org_id=other_org.id, name="Cross", slug="cross")
    db_session.add_all([team, other_team, cross_org_team])
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
    cross_org_project = Project(
        org_id=other_org.id,
        team_id=cross_org_team.id,
        created_by=uuid4(),
        name="Cross",
        slug="cross",
    )
    db_session.add_all([project, other_project, cross_org_project])
    await db_session.commit()
    return org, team, project, other_team, other_project, cross_org_project


async def test_org_admin_can_view_team_and_project_without_memberships(
    db_session: AsyncSession,
) -> None:
    org, team, project, _, _, _ = await _workspace(db_session)
    user = _user(
        org_id=org.id,
        role="org_admin",
        permissions=["teams.view", "projects.view"],
    )

    await require_team_view_or_permission(
        team_id=str(team.id),
        permission="teams.view",
        user=user,
        db=db_session,
    )
    await require_project_view_or_permission(
        project_id=str(project.id),
        permission="projects.view",
        user=user,
        db=db_session,
    )


async def test_team_member_can_view_own_team_project_but_not_other_team(
    db_session: AsyncSession,
) -> None:
    org, team, project, other_team, _, _ = await _workspace(db_session)
    user = _user(org_id=org.id)
    db_session.add(_user_row(user))
    db_session.add(
        TeamMembership(
            org_id=org.id,
            team_id=team.id,
            user_id=user.id,
            role="team_member",
        )
    )
    await db_session.commit()

    await require_team_view_or_permission(
        team_id=str(team.id),
        permission="teams.view",
        user=user,
        db=db_session,
    )
    await require_project_view_or_permission(
        project_id=str(project.id),
        permission="projects.view",
        user=user,
        db=db_session,
    )
    with pytest.raises(HTTPException) as exc:
        await require_team_view_or_permission(
            team_id=str(other_team.id),
            permission="teams.view",
            user=user,
            db=db_session,
        )

    assert exc.value.status_code == 403


async def test_project_admin_can_view_own_project_but_not_cross_project_or_org(
    db_session: AsyncSession,
) -> None:
    org, _, project, _, other_project, cross_org_project = await _workspace(db_session)
    user = _user(org_id=org.id)
    db_session.add(_user_row(user))
    db_session.add(
        ProjectMembership(
            org_id=org.id,
            project_id=project.id,
            user_id=user.id,
            role="project_admin",
        )
    )
    await db_session.commit()

    await require_project_view_or_permission(
        project_id=str(project.id),
        permission="projects.view",
        user=user,
        db=db_session,
    )
    for blocked_project in (other_project, cross_org_project):
        with pytest.raises(HTTPException) as exc:
            await require_project_view_or_permission(
                project_id=str(blocked_project.id),
                permission="projects.view",
                user=user,
                db=db_session,
            )
        assert exc.value.status_code == 403
