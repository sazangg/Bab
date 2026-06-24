from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    require_project_team_admin_or_permission,
    require_project_view_or_permission,
    require_team_view_or_permission,
)
from app.api.v1.routes.guardrails import _require_assignment_admin as require_guardrail_assignment
from app.api.v1.routes.guardrails import create_assignment as create_guardrail_assignment
from app.api.v1.routes.guardrails import update_assignment as update_guardrail_assignment
from app.api.v1.routes.policies import _require_assignment_admin as require_policy_assignment
from app.api.v1.routes.policies import create_policy_assignment
from app.core.database import Scope
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
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.guardrails.schemas import (
    CreateGuardrailAssignmentRequest,
    CreateGuardrailPolicyRequest,
    UpdateGuardrailAssignmentRequest,
)
from app.modules.keys.internal.models import Project, VirtualKey
from app.modules.policies import facade as policies_facade
from app.modules.policies.schemas import CreateLimitPolicyRequest, CreatePolicyAssignmentRequest


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
    await db_session.flush()
    key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Runtime key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab-test",
    )
    other_key = VirtualKey(
        org_id=org.id,
        project_id=other_project.id,
        name="Other key",
        key_hash=f"hash-{uuid4()}",
        key_prefix="bab-test",
    )
    db_session.add_all([key, other_key])
    await db_session.commit()
    return org, team, project, other_team, other_project, cross_org_project, key, other_key


async def test_org_admin_can_view_team_and_project_without_memberships(
    db_session: AsyncSession,
) -> None:
    org, team, project, _, _, _, _, _ = await _workspace(db_session)
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
    org, team, project, other_team, _, _, _, _ = await _workspace(db_session)
    user = _user(org_id=org.id)
    db_session.add(_user_row(user))
    await db_session.flush()
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
    org, _, project, _, other_project, cross_org_project, _, _ = await _workspace(db_session)
    user = _user(org_id=org.id)
    db_session.add(_user_row(user))
    await db_session.flush()
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


async def test_project_member_can_view_only_own_project_and_cannot_manage_it(
    db_session: AsyncSession,
) -> None:
    org, _, project, _, other_project, _, _, _ = await _workspace(db_session)
    user = _user(org_id=org.id)
    db_session.add(_user_row(user))
    await db_session.flush()
    db_session.add(
        ProjectMembership(
            org_id=org.id,
            project_id=project.id,
            user_id=user.id,
            role="project_member",
        )
    )
    await db_session.commit()

    await require_project_view_or_permission(
        project_id=str(project.id),
        permission="projects.view",
        user=user,
        db=db_session,
    )
    with pytest.raises(HTTPException) as cross_project:
        await require_project_view_or_permission(
            project_id=str(other_project.id),
            permission="projects.view",
            user=user,
            db=db_session,
        )
    manage_project = require_project_team_admin_or_permission("projects.manage")
    with pytest.raises(HTTPException) as manage:
        await manage_project(project_id=str(project.id), user=user, db=db_session)

    assert cross_project.value.status_code == 403
    assert manage.value.status_code == 403


@pytest.mark.parametrize("guard", [require_policy_assignment, require_guardrail_assignment])
async def test_org_admin_can_manage_any_policy_assignment_scope(
    db_session: AsyncSession,
    guard,
) -> None:
    (
        org,
        _team,
        _project,
        _other_team,
        _other_project,
        _cross_org_project,
        _key,
        _other_key,
    ) = await _workspace(db_session)
    user = _user(org_id=org.id, role="org_admin")

    await guard(
        user=user,
        scope_type="org",
        team_id=None,
        project_id=None,
        virtual_key_id=None,
        scope=Scope(org_id=org.id),
        db=db_session,
    )


@pytest.mark.parametrize("guard", [require_policy_assignment, require_guardrail_assignment])
async def test_team_admin_can_manage_team_projects_and_keys(
    db_session: AsyncSession,
    guard,
) -> None:
    (
        org,
        team,
        project,
        _other_team,
        _other_project,
        _cross_org_project,
        key,
        _other_key,
    ) = await _workspace(db_session)
    user = _user(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )

    for scope_type, team_id, project_id, virtual_key_id in (
        ("team", team.id, None, None),
        ("project", None, project.id, None),
        ("virtual_key", None, None, key.id),
    ):
        await guard(
            user=user,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            scope=Scope(org_id=org.id),
            db=db_session,
        )


@pytest.mark.parametrize("guard", [require_policy_assignment, require_guardrail_assignment])
async def test_project_admin_can_manage_project_and_keys_but_not_team_or_org(
    db_session: AsyncSession,
    guard,
) -> None:
    (
        org,
        team,
        project,
        _other_team,
        _other_project,
        _cross_org_project,
        key,
        _other_key,
    ) = await _workspace(db_session)
    user = _user(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    for scope_type, team_id, project_id, virtual_key_id in (
        ("project", None, project.id, None),
        ("virtual_key", None, None, key.id),
    ):
        await guard(
            user=user,
            scope_type=scope_type,
            team_id=team_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            scope=Scope(org_id=org.id),
            db=db_session,
        )

    for scope_type, team_id, project_id, virtual_key_id in (
        ("org", None, None, None),
        ("team", team.id, None, None),
    ):
        with pytest.raises(HTTPException) as exc:
            await guard(
                user=user,
                scope_type=scope_type,
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
                scope=Scope(org_id=org.id),
                db=db_session,
            )
        assert exc.value.status_code == 403


@pytest.mark.parametrize("guard", [require_policy_assignment, require_guardrail_assignment])
async def test_unrelated_scoped_admin_cannot_manage_assignment_targets(
    db_session: AsyncSession,
    guard,
) -> None:
    (
        org,
        _team,
        project,
        other_team,
        _other_project,
        _cross_org_project,
        key,
        _other_key,
    ) = await _workspace(db_session)
    user = _user(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=other_team.id, role="team_admin")],
    )

    for scope_type, team_id, project_id, virtual_key_id in (
        ("project", None, project.id, None),
        ("virtual_key", None, None, key.id),
    ):
        with pytest.raises(HTTPException) as exc:
            await guard(
                user=user,
                scope_type=scope_type,
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
                scope=Scope(org_id=org.id),
                db=db_session,
            )
        assert exc.value.status_code == 403


async def _guardrail_assignment(*, db_session: AsyncSession, org_id, scope_type: str, **ids):
    actor = _user(org_id=org_id, role="org_admin")
    scope = Scope(org_id=org_id)
    policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(name=f"Guard {uuid4()}"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    assignment = await guardrails_facade.create_assignment(
        payload=CreateGuardrailAssignmentRequest(
            policy_id=policy.id,
            scope_type=scope_type,
            **ids,
        ),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    return policy, assignment


async def _limit_policy(*, db_session: AsyncSession, org_id):
    actor = _user(org_id=org_id, role="org_admin")
    return await policies_facade.create_limit_policy(
        payload=CreateLimitPolicyRequest(name=f"Limit {uuid4()}"),
        actor=actor,
        scope=Scope(org_id=org_id),
        db=db_session,
    )


async def test_assignment_routes_reject_cross_org_team_targets(
    db_session: AsyncSession,
) -> None:
    org, _team, _project, _other_team, _other_project, cross_org_project, *_ = await _workspace(
        db_session
    )
    actor = _user(org_id=org.id, role="org_admin")
    limit = await _limit_policy(db_session=db_session, org_id=org.id)
    guardrail_policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(name=f"Guard {uuid4()}"),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    with pytest.raises(HTTPException) as policy_exc:
        await create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_id=limit.policy_id,
                policy_type="limit",
                scope_type="team",
                team_id=cross_org_project.team_id,
            ),
            _user=actor,
            scope=Scope(org_id=org.id),
            db=db_session,
        )
    with pytest.raises(HTTPException) as guardrail_exc:
        await create_guardrail_assignment(
            payload=CreateGuardrailAssignmentRequest(
                policy_id=guardrail_policy.id,
                scope_type="team",
                team_id=cross_org_project.team_id,
            ),
            actor=actor,
            scope=Scope(org_id=org.id),
            db=db_session,
        )

    assert policy_exc.value.status_code == 404
    assert guardrail_exc.value.status_code == 404


async def test_assignment_routes_reject_project_team_mismatch(
    db_session: AsyncSession,
) -> None:
    org, _team, project, other_team, *_ = await _workspace(db_session)
    actor = _user(org_id=org.id, role="org_admin")
    limit = await _limit_policy(db_session=db_session, org_id=org.id)
    guardrail_policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(name=f"Guard {uuid4()}"),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    with pytest.raises(HTTPException) as policy_exc:
        await create_policy_assignment(
            payload=CreatePolicyAssignmentRequest(
                policy_id=limit.policy_id,
                policy_type="limit",
                scope_type="project",
                team_id=other_team.id,
                project_id=project.id,
            ),
            _user=actor,
            scope=Scope(org_id=org.id),
            db=db_session,
        )
    with pytest.raises(HTTPException) as guardrail_exc:
        await create_guardrail_assignment(
            payload=CreateGuardrailAssignmentRequest(
                policy_id=guardrail_policy.id,
                scope_type="project",
                team_id=other_team.id,
                project_id=project.id,
            ),
            actor=actor,
            scope=Scope(org_id=org.id),
            db=db_session,
        )

    assert policy_exc.value.status_code == 400
    assert guardrail_exc.value.status_code == 404


async def test_assignment_routes_reject_virtual_key_parent_mismatches(
    db_session: AsyncSession,
) -> None:
    org, _team, _project, other_team, other_project, _cross_org, key, _other_key = await _workspace(
        db_session
    )
    actor = _user(org_id=org.id, role="org_admin")
    limit = await _limit_policy(db_session=db_session, org_id=org.id)
    guardrail_policy = await guardrails_facade.create_policy(
        payload=CreateGuardrailPolicyRequest(name=f"Guard {uuid4()}"),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    for project_id, team_id in ((other_project.id, None), (None, other_team.id)):
        with pytest.raises(HTTPException) as policy_exc:
            await create_policy_assignment(
                payload=CreatePolicyAssignmentRequest(
                    policy_id=limit.policy_id,
                    policy_type="limit",
                    scope_type="virtual_key",
                    project_id=project_id,
                    team_id=team_id,
                    virtual_key_id=key.id,
                ),
                _user=actor,
                scope=Scope(org_id=org.id),
                db=db_session,
            )
        with pytest.raises(HTTPException) as guardrail_exc:
            await create_guardrail_assignment(
                payload=CreateGuardrailAssignmentRequest(
                    policy_id=guardrail_policy.id,
                    scope_type="virtual_key",
                    project_id=project_id,
                    team_id=team_id,
                    virtual_key_id=key.id,
                ),
                actor=actor,
                scope=Scope(org_id=org.id),
                db=db_session,
            )
        assert policy_exc.value.status_code == 400
        assert guardrail_exc.value.status_code == 404


async def test_project_admin_cannot_move_other_project_guardrail_assignment(
    db_session: AsyncSession,
) -> None:
    org, _team, project, _other_team, other_project, *_ = await _workspace(db_session)
    _policy, assignment = await _guardrail_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=project.id,
    )
    actor = _user(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=other_project.id, role="project_admin")
        ],
    )

    with pytest.raises(HTTPException) as exc:
        await update_guardrail_assignment(
            assignment_id=assignment.id,
            payload=UpdateGuardrailAssignmentRequest(
                scope_type="project",
                project_id=other_project.id,
            ),
            actor=actor,
            scope=Scope(org_id=org.id),
            db=db_session,
        )

    assert exc.value.status_code == 403


async def test_project_admin_cannot_move_org_guardrail_assignment_to_project(
    db_session: AsyncSession,
) -> None:
    org, _team, project, *_ = await _workspace(db_session)
    _policy, assignment = await _guardrail_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="org",
    )
    actor = _user(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    with pytest.raises(HTTPException) as exc:
        await update_guardrail_assignment(
            assignment_id=assignment.id,
            payload=UpdateGuardrailAssignmentRequest(
                scope_type="project",
                project_id=project.id,
            ),
            actor=actor,
            scope=Scope(org_id=org.id),
            db=db_session,
        )

    assert exc.value.status_code == 403


async def test_project_admin_can_update_own_project_guardrail_assignment(
    db_session: AsyncSession,
) -> None:
    org, _team, project, *_ = await _workspace(db_session)
    _policy, assignment = await _guardrail_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=project.id,
    )
    actor = _user(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )

    updated = await update_guardrail_assignment(
        assignment_id=assignment.id,
        payload=UpdateGuardrailAssignmentRequest(enforcement_mode="dry_run", is_active=False),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    assert updated.enforcement_mode == "dry_run"
    assert updated.is_active is False


async def test_team_admin_can_move_guardrail_assignment_only_within_team(
    db_session: AsyncSession,
) -> None:
    org, team, project, _other_team, other_project, *_ = await _workspace(db_session)
    _policy, assignment = await _guardrail_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=project.id,
    )
    actor = _user(
        org_id=org.id,
        team_memberships=[AuthenticatedTeamMembership(team_id=team.id, role="team_admin")],
    )

    moved = await update_guardrail_assignment(
        assignment_id=assignment.id,
        payload=UpdateGuardrailAssignmentRequest(scope_type="team", team_id=team.id),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )
    assert moved.scope_type == "team"
    assert moved.team_id == team.id

    with pytest.raises(HTTPException) as exc:
        await update_guardrail_assignment(
            assignment_id=assignment.id,
            payload=UpdateGuardrailAssignmentRequest(
                scope_type="project",
                project_id=other_project.id,
            ),
            actor=actor,
            scope=Scope(org_id=org.id),
            db=db_session,
        )
    assert exc.value.status_code == 403


async def test_global_guardrail_manager_can_update_any_assignment(
    db_session: AsyncSession,
) -> None:
    org, _team, project, *_ = await _workspace(db_session)
    _policy, assignment = await _guardrail_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=project.id,
    )
    actor = _user(org_id=org.id, permissions=["guardrails.manage"])

    updated = await update_guardrail_assignment(
        assignment_id=assignment.id,
        payload=UpdateGuardrailAssignmentRequest(is_active=False),
        actor=actor,
        scope=Scope(org_id=org.id),
        db=db_session,
    )

    assert updated.is_active is False


async def test_project_admin_guardrail_reads_are_limited_to_own_project(
    db_session: AsyncSession,
) -> None:
    org, _team, project, _other_team, other_project, _cross_org, key, other_key = await _workspace(
        db_session
    )
    own_policy, own_assignment = await _guardrail_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=project.id,
    )
    other_policy, _other_assignment = await _guardrail_assignment(
        db_session=db_session,
        org_id=org.id,
        scope_type="project",
        project_id=other_project.id,
    )
    for policy, target_project, target_key in (
        (own_policy, project, key),
        (other_policy, other_project, other_key),
    ):
        await guardrails_repository.create_event(
            org_id=org.id,
            policy_id=policy.id,
            policy_revision_id=None,
            rule_id=None,
            decision="blocked",
            phase="request",
            reason="test",
            team_id=target_project.team_id,
            project_id=target_project.id,
            virtual_key_id=target_key.id,
            provider_id=uuid4(),
            pool_id=uuid4(),
            request_id=None,
            requested_model="test-model",
            provider_model="test-model",
            metadata={},
            db=db_session,
        )
    await db_session.commit()
    actor = _user(
        org_id=org.id,
        project_memberships=[
            AuthenticatedProjectMembership(project_id=project.id, role="project_admin")
        ],
    )
    scope = Scope(org_id=org.id)

    assignments = await guardrails_facade.list_assignments(
        scope=scope,
        db=db_session,
        actor=actor,
    )
    policies = await guardrails_facade.list_policies(
        scope=scope,
        db=db_session,
        actor=actor,
    )
    events = await guardrails_facade.list_events(
        scope=scope,
        db=db_session,
        actor=actor,
    )

    assert [assignment.id for assignment in assignments] == [own_assignment.id]
    assert [policy.id for policy in policies] == [own_policy.id]
    assert [event.project_id for event in events] == [project.id]
