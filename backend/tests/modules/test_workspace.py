from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import (
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
)
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.errors import WorkspaceAccessDeniedError, WorkspaceScopeNotFoundError


async def _workspace(db_session: AsyncSession):
    org = Organization(name=f"Access {uuid4()}", slug=f"access-{uuid4()}")
    other_org = Organization(name=f"Other {uuid4()}", slug=f"other-{uuid4()}")
    db_session.add_all([org, other_org])
    await db_session.flush()
    team = Team(org_id=org.id, name="Platform", slug=f"platform-{uuid4()}")
    other_team = Team(org_id=org.id, name="Billing", slug=f"billing-{uuid4()}")
    db_session.add_all([team, other_team])
    await db_session.flush()
    project = Project(
        org_id=org.id,
        team_id=team.id,
        created_by=uuid4(),
        name="Gateway",
        slug=f"gateway-{uuid4()}",
    )
    other_project = Project(
        org_id=org.id,
        team_id=other_team.id,
        created_by=uuid4(),
        name="Console",
        slug=f"console-{uuid4()}",
    )
    db_session.add_all([project, other_project])
    await db_session.flush()
    key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Runtime key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab_test",
    )
    other_org_key = VirtualKey(
        org_id=other_org.id,
        project_id=project.id,
        name="Wrong org key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab_test",
    )
    db_session.add_all([key, other_org_key])
    await db_session.flush()
    return org, team, other_team, project, other_project, key, other_org_key


def _actor(
    org_id,
    *,
    role: str = "org_member",
    permissions: list[str] | None = None,
    team_memberships: list[AuthenticatedTeamMembership] | None = None,
    project_memberships: list[AuthenticatedProjectMembership] | None = None,
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        org_id=org_id,
        email="actor@example.com",
        role=role,
        permissions=permissions or [],
        team_memberships=team_memberships or [],
        project_memberships=project_memberships or [],
    )


@pytest.mark.asyncio
async def test_validate_assignment_scope_normalizes_known_targets(
    db_session: AsyncSession,
) -> None:
    org, team, _other_team, project, _other_project, key, _other_org_key = await _workspace(
        db_session
    )
    org_scope = await workspace_facade.validate_assignment_scope(
        organization_id=org.id,
        scope_type="org",
        db=db_session,
    )
    team_scope = await workspace_facade.validate_assignment_scope(
        organization_id=org.id,
        scope_type="team",
        team_id=team.id,
        db=db_session,
    )
    project_scope = await workspace_facade.validate_assignment_scope(
        organization_id=org.id,
        scope_type="project",
        team_id=team.id,
        project_id=project.id,
        db=db_session,
    )
    key_scope = await workspace_facade.validate_assignment_scope(
        organization_id=org.id,
        scope_type="virtual_key",
        team_id=team.id,
        project_id=project.id,
        virtual_key_id=key.id,
        db=db_session,
    )

    assert org_scope.scope_type == "org"
    assert team_scope.team_id == team.id
    assert project_scope.project_id == project.id
    assert key_scope.virtual_key_id == key.id


@pytest.mark.asyncio
async def test_validate_assignment_scope_rejects_invalid_relationships(
    db_session: AsyncSession,
) -> None:
    org, _team, other_team, project, other_project, key, other_org_key = await _workspace(
        db_session
    )
    with pytest.raises(WorkspaceScopeNotFoundError):
        await workspace_facade.validate_assignment_scope(
            organization_id=org.id,
            scope_type="project",
            team_id=other_team.id,
            project_id=project.id,
            db=db_session,
        )
    with pytest.raises(WorkspaceScopeNotFoundError):
        await workspace_facade.validate_assignment_scope(
            organization_id=org.id,
            scope_type="virtual_key",
            project_id=other_project.id,
            virtual_key_id=key.id,
            db=db_session,
        )
    with pytest.raises(WorkspaceScopeNotFoundError):
        await workspace_facade.validate_assignment_scope(
            organization_id=org.id,
            scope_type="virtual_key",
            virtual_key_id=other_org_key.id,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_require_assignment_admin_allows_matching_scoped_admins(
    db_session: AsyncSession,
) -> None:
    org, team, _other_team, project, _other_project, key, _other_org_key = await _workspace(
        db_session
    )
    scope = Scope(org_id=org.id)

    await workspace_facade.require_assignment_admin(
        actor=_actor(
            org.id,
            team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
        ),
        scope=scope,
        scope_type="team",
        team_id=team.id,
        db=db_session,
    )
    await workspace_facade.require_assignment_admin(
        actor=_actor(
            org.id,
            project_memberships=[
                AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
            ],
        ),
        scope=scope,
        scope_type="project",
        project_id=project.id,
        db=db_session,
    )
    await workspace_facade.require_assignment_admin(
        actor=_actor(
            org.id,
            team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
        ),
        scope=scope,
        scope_type="virtual_key",
        virtual_key_id=key.id,
        db=db_session,
    )


@pytest.mark.asyncio
async def test_require_assignment_admin_preserves_global_permission_boundary(
    db_session: AsyncSession,
) -> None:
    org, _team, _other_team, _project, _other_project, _key, _other_org_key = await _workspace(
        db_session
    )
    scope = Scope(org_id=org.id)

    with pytest.raises(WorkspaceAccessDeniedError):
        await workspace_facade.require_assignment_admin(
            actor=_actor(org.id, permissions=["guardrails.manage"]),
            scope=scope,
            scope_type="org",
            db=db_session,
        )
    await workspace_facade.require_assignment_admin(
        actor=_actor(org.id, permissions=["guardrails.manage"]),
        scope=scope,
        scope_type="org",
        global_permissions={"guardrails.manage"},
        db=db_session,
    )


@pytest.mark.asyncio
async def test_require_assignment_admin_denies_unmanaged_scope(
    db_session: AsyncSession,
) -> None:
    org, _team, other_team, project, _other_project, key, _other_org_key = await _workspace(
        db_session
    )
    actor = _actor(
        org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=other_team.id, role="team_admin")],
    )

    with pytest.raises(WorkspaceAccessDeniedError):
        await workspace_facade.require_assignment_admin(
            actor=actor,
            scope=Scope(org_id=org.id),
            scope_type="project",
            project_id=project.id,
            db=db_session,
        )
    with pytest.raises(WorkspaceAccessDeniedError):
        await workspace_facade.require_assignment_admin(
            actor=actor,
            scope=Scope(org_id=org.id),
            scope_type="virtual_key",
            virtual_key_id=key.id,
            db=db_session,
        )
