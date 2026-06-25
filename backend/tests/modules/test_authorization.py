from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import (
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
)
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.errors import AuthorizationDeniedError
from app.modules.authorization.permissions import Permissions
from app.modules.authorization.schemas import (
    AuthorizationTarget,
    MemberInviteTarget,
    MemberRoleChangeTarget,
    ScopedMembershipTarget,
)
from app.modules.keys.internal.models import VirtualKey
from app.modules.workspace.internal.models import Project, Team


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
    db_session.add(key)
    await db_session.flush()
    return org, team, other_team, project, other_project, key


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


def _target(scope_type: str, **ids) -> AuthorizationTarget:
    return AuthorizationTarget.assignment_scope(scope_type=scope_type, **ids)


@pytest.mark.asyncio
async def test_org_admin_can_assign_policies_at_any_scope(db_session: AsyncSession) -> None:
    org, team, _other_team, project, _other_project, key = await _workspace(db_session)
    actor = _actor(org.id, role="org_admin", permissions=[Permissions.POLICIES_ASSIGN])

    for target in (
        _target("org"),
        _target("team", team_id=team.id),
        _target("project", project_id=project.id),
        _target("virtual_key", virtual_key_id=key.id),
    ):
        decision = await authorization_facade.can(
            actor=actor,
            permission=Permissions.POLICIES_ASSIGN,
            target=target,
            scope=Scope(org_id=org.id),
            db=db_session,
        )

        assert decision.allowed is True
        assert decision.reason_code == "permission_grant"


@pytest.mark.asyncio
async def test_org_viewer_cannot_assign(db_session: AsyncSession) -> None:
    org, team, _other_team, _project, _other_project, _key = await _workspace(db_session)

    decision = await authorization_facade.can(
        actor=_actor(org.id, role="org_viewer", permissions=[Permissions.POLICIES_VIEW]),
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("team", team_id=team.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    assert decision.allowed is False
    assert decision.reason_code == "missing_permission"


@pytest.mark.asyncio
async def test_team_admin_can_assign_within_team_only(db_session: AsyncSession) -> None:
    org, team, other_team, project, other_project, _key = await _workspace(db_session)
    actor = _actor(
        org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )

    own_team = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("team", team_id=team.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    own_project = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("project", project_id=project.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    outside_team = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("team", team_id=other_team.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    outside_project = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("project", project_id=other_project.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    assert own_team.reason_code == "scoped_team_admin"
    assert own_project.reason_code == "scoped_team_admin"
    assert outside_team.allowed is False
    assert outside_project.allowed is False


@pytest.mark.asyncio
async def test_project_admin_can_assign_project_and_key_but_not_org(
    db_session: AsyncSession,
) -> None:
    org, _team, _other_team, project, _other_project, key = await _workspace(db_session)
    actor = _actor(
        org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    project_decision = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("project", project_id=project.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    key_decision = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("virtual_key", virtual_key_id=key.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    org_decision = await authorization_facade.can(
        actor=actor,
        permission=Permissions.POLICIES_ASSIGN,
        target=_target("org"),
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    assert project_decision.reason_code == "scoped_project_admin"
    assert key_decision.reason_code == "scoped_project_admin"
    assert org_decision.allowed is False


@pytest.mark.asyncio
async def test_guardrail_assignment_uses_guardrail_permission(db_session: AsyncSession) -> None:
    org, team, _other_team, _project, _other_project, _key = await _workspace(db_session)
    actor = _actor(org.id, role="org_admin", permissions=[Permissions.GUARDRAILS_ASSIGN])

    decision = await authorization_facade.require(
        actor=actor,
        permission=Permissions.GUARDRAILS_ASSIGN,
        target=_target("team", team_id=team.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    assert decision.allowed is True
    assert decision.matched_permission == Permissions.GUARDRAILS_ASSIGN


@pytest.mark.asyncio
async def test_workspace_scope_uses_read_permission_and_scoped_admins(
    db_session: AsyncSession,
) -> None:
    org, team, _other_team, project, _other_project, key = await _workspace(db_session)
    viewer = _actor(org.id, role="org_viewer")
    team_admin = _actor(
        org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )
    project_admin = _actor(
        org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    org_decision = await authorization_facade.can(
        actor=viewer,
        permission=Permissions.POLICIES_VIEW,
        target=AuthorizationTarget.workspace_scope(scope_type="org"),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    team_decision = await authorization_facade.can(
        actor=team_admin,
        permission=Permissions.POLICIES_VIEW,
        target=AuthorizationTarget.workspace_scope(scope_type="team", team_id=team.id),
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    key_decision = await authorization_facade.can(
        actor=project_admin,
        permission=Permissions.POLICIES_VIEW,
        target=AuthorizationTarget.workspace_scope(
            scope_type="virtual_key",
            virtual_key_id=key.id,
        ),
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    assert org_decision.reason_code == "permission_grant"
    assert team_decision.reason_code == "scoped_team_admin"
    assert key_decision.reason_code == "scoped_project_admin"


def test_scoped_admin_workspace_ids() -> None:
    team_id = uuid4()
    project_id = uuid4()
    actor = _actor(
        uuid4(),
        team_memberships=[AuthenticatedTeamMembership(team_id=team_id, role="team_admin")],
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project_id, role="project_admin")
        ],
    )

    scopes = authorization_facade.scoped_admin_workspace_ids(actor)

    assert scopes.team_ids == {team_id}
    assert scopes.project_ids == {project_id}


def test_org_admin_cannot_manage_protected_roles() -> None:
    actor = _actor(uuid4(), role="org_admin")

    allowed = authorization_facade.can_manage_org_role(
        actor=actor,
        target=MemberRoleChangeTarget(current_role="org_member", new_role="org_viewer"),
    )
    denied = authorization_facade.can_manage_org_role(
        actor=actor,
        target=MemberRoleChangeTarget(current_role="org_member", new_role="org_admin"),
    )

    assert allowed.reason_code == "org_admin_role_grant"
    assert denied.allowed is False
    assert denied.reason_code == "protected_role_denied"


def test_scoped_admin_invite_and_membership_decisions() -> None:
    team_id = uuid4()
    project_id = uuid4()
    actor = _actor(
        uuid4(),
        team_memberships=[AuthenticatedTeamMembership(team_id=team_id, role="team_admin")],
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project_id, role="project_admin")
        ],
    )

    team_invite = authorization_facade.can_create_member_invite(
        actor=actor,
        target=MemberInviteTarget(org_role="org_member", team_id=team_id, team_role="team_member"),
    )
    project_members = authorization_facade.can_manage_scoped_membership(
        actor=actor,
        permission=Permissions.PROJECTS_MANAGE,
        target=ScopedMembershipTarget(
            scope_type="project",
            project_id=project_id,
            project_team_id=uuid4(),
        ),
    )

    assert team_invite.reason_code == "scoped_team_admin"
    assert project_members.reason_code == "scoped_project_admin"


def test_effective_permissions_for_member_adds_scoped_admin_grants() -> None:
    permissions = authorization_facade.effective_permissions_for_member(
        org_role="org_member",
        team_roles=["team_admin"],
        project_roles=["project_admin"],
    )

    assert Permissions.KEYS_MANAGE in permissions
    assert Permissions.TEAMS_VIEW in permissions
    assert Permissions.PROJECTS_VIEW in permissions


@pytest.mark.asyncio
async def test_require_raises_denied_error(db_session: AsyncSession) -> None:
    org, _team, _other_team, _project, _other_project, _key = await _workspace(db_session)

    with pytest.raises(AuthorizationDeniedError) as exc:
        await authorization_facade.require(
            actor=_actor(org.id),
            permission=Permissions.POLICIES_ASSIGN,
            target=_target("org"),
            scope=Scope(org_id=org.id),
            db=db_session,
        )

    assert exc.value.decision.allowed is False
