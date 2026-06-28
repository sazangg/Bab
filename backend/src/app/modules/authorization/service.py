from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth import facade as auth_facade
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization.errors import AuthorizationDeniedError
from app.modules.authorization.grants import ROLE_PERMISSIONS
from app.modules.authorization.permissions import Permissions
from app.modules.authorization.schemas import (
    AuthorizationDecision,
    AuthorizationTarget,
    AuthorizedWorkspaceScopes,
    MemberInviteTarget,
    MemberRoleChangeTarget,
    MemberStatusChangeTarget,
    ScopedMembershipTarget,
)
from app.modules.workspace import facade as workspace_facade


async def can(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    scope: Scope,
    db: AsyncSession,
) -> AuthorizationDecision:
    if target.kind == "assignment_scope":
        return await can_manage_assignment_scope(
            actor=actor,
            permission=permission,
            target=target,
            scope=scope,
            db=db,
        )
    if target.kind == "workspace_scope":
        return await can_access_workspace_scope(
            actor=actor,
            permission=permission,
            target=target,
            scope=scope,
            db=db,
        )
    return _decision(
        actor=actor,
        permission=permission,
        target=target,
        allowed=False,
        reason_code="invalid_target",
    )


def has_permission(actor: AuthenticatedUser, permission: str) -> bool:
    return has_any_permission(actor, {permission})


def has_any_permission(actor: AuthenticatedUser, permissions: set[str]) -> bool:
    actor_permissions = _effective_permissions(actor)
    return Permissions.WILDCARD in actor_permissions or bool(
        actor_permissions.intersection(permissions)
    )


def has_any_role(actor: AuthenticatedUser, roles: set[str]) -> bool:
    return Permissions.WILDCARD in _effective_permissions(actor) or actor.role in roles


def can_manage_org_role(
    *,
    actor: AuthenticatedUser,
    target: MemberRoleChangeTarget,
) -> AuthorizationDecision:
    if Permissions.WILDCARD in _effective_permissions(actor) or actor.role == "org_owner":
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="org_owner_role_grant",
            allowed=True,
            matched_permission=Permissions.WILDCARD
            if Permissions.WILDCARD in _effective_permissions(actor)
            else None,
        )
    if actor.role != "org_admin":
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="missing_permission",
            allowed=False,
        )
    if target.current_role in {"org_owner", "org_admin"} or target.new_role in {
        "org_owner",
        "org_admin",
    }:
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="protected_role_denied",
            allowed=False,
        )
    return _member_decision(
        actor=actor,
        permission=Permissions.MEMBERS_MANAGE,
        reason_code="org_admin_role_grant",
        allowed=True,
    )


def can_change_member_status(
    *,
    actor: AuthenticatedUser,
    target: MemberStatusChangeTarget,
) -> AuthorizationDecision:
    if (
        target.new_status == "inactive"
        and actor.id == target.target_user_id
        and has_permission(actor, Permissions.MEMBERS_MANAGE)
    ):
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="self_deactivation_denied",
            allowed=False,
        )
    return can_manage_org_role(
        actor=actor,
        target=MemberRoleChangeTarget(
            target_user_id=target.target_user_id,
            current_role=target.current_role,
            new_role=target.current_role,
        ),
    )


def can_change_member_role_without_self_demotion(
    *,
    actor: AuthenticatedUser,
    target: MemberRoleChangeTarget,
) -> AuthorizationDecision:
    decision = can_manage_org_role(actor=actor, target=target)
    if not decision.allowed:
        return decision
    if (
        target.target_user_id == actor.id
        and target.current_role != target.new_role
        and has_permission(actor, Permissions.MEMBERS_MANAGE)
        and target.new_role not in {"org_owner", "org_admin"}
    ):
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="self_demotion_denied",
            allowed=False,
        )
    return decision


def can_create_member_invite(
    *,
    actor: AuthenticatedUser,
    target: MemberInviteTarget,
) -> AuthorizationDecision:
    if has_permission(actor, Permissions.MEMBERS_MANAGE):
        return can_manage_org_role(
            actor=actor,
            target=MemberRoleChangeTarget(current_role=None, new_role=target.org_role),
        )
    if target.org_role != "org_member":
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="protected_role_denied",
            allowed=False,
        )
    return _scoped_invite_decision(actor=actor, target=target, creating=True)


def can_manage_member_invite(
    *,
    actor: AuthenticatedUser,
    target: MemberInviteTarget,
) -> AuthorizationDecision:
    if has_permission(actor, Permissions.MEMBERS_MANAGE):
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="permission_grant",
            allowed=True,
            matched_permission=Permissions.MEMBERS_MANAGE,
        )
    return _scoped_invite_decision(actor=actor, target=target, creating=False)


def can_manage_scoped_membership(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: ScopedMembershipTarget,
) -> AuthorizationDecision:
    grant = _member_grant_decision(actor=actor, permission=permission)
    if grant is not None:
        return grant
    if target.scope_type == "team":
        if target.team_id is not None and target.team_id in _team_admin_ids(actor):
            return _member_decision(
                actor=actor,
                permission=permission,
                reason_code="scoped_team_admin",
                allowed=True,
            )
    if target.scope_type == "project":
        if target.project_team_id is not None and target.project_team_id in _team_admin_ids(actor):
            return _member_decision(
                actor=actor,
                permission=permission,
                reason_code="scoped_team_admin",
                allowed=True,
            )
        if target.project_id is not None and target.project_id in _project_admin_ids(actor):
            return _member_decision(
                actor=actor,
                permission=permission,
                reason_code="scoped_project_admin",
                allowed=True,
            )
    return _member_decision(
        actor=actor,
        permission=permission,
        reason_code="missing_permission",
        allowed=False,
    )


def effective_permissions_for_member(
    *,
    org_role: str,
    team_roles: list[str],
    project_roles: list[str],
) -> list[str]:
    permissions = set(ROLE_PERMISSIONS.get(org_role, set()))
    if "team_admin" in team_roles:
        permissions.update(
            {
                Permissions.KEYS_MANAGE,
                Permissions.POLICIES_VIEW,
                Permissions.GUARDRAILS_VIEW,
                Permissions.PROJECTS_VIEW,
                Permissions.TEAMS_VIEW,
            }
        )
    if "project_admin" in project_roles:
        permissions.update(
            {
                Permissions.KEYS_MANAGE,
                Permissions.POLICIES_VIEW,
                Permissions.GUARDRAILS_VIEW,
                Permissions.PROJECTS_VIEW,
            }
        )
    return sorted(permissions)


def authorized_workspace_ids(
    actor: AuthenticatedUser,
    *,
    relationship: str,
) -> AuthorizedWorkspaceScopes:
    if relationship == "admin":
        return AuthorizedWorkspaceScopes(
            team_ids=_team_admin_ids(actor),
            project_ids=_project_admin_ids(actor),
        )
    return AuthorizedWorkspaceScopes(
        team_ids=_team_member_ids(actor),
        project_ids=_project_member_ids(actor),
    )


def scoped_admin_workspace_ids(actor: AuthenticatedUser) -> AuthorizedWorkspaceScopes:
    return authorized_workspace_ids(actor, relationship="admin")


async def can_access_workspace_scope(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    scope: Scope,
    db: AsyncSession,
) -> AuthorizationDecision:
    grant = _grant_decision(actor=actor, permission=permission, target=target)
    if grant is not None:
        return grant
    if target.scope_type == "org":
        return _decision(
            actor=actor,
            permission=permission,
            target=target,
            allowed=False,
            reason_code="missing_permission",
        )
    reason_code = await _scoped_workspace_reason(actor=actor, target=target, scope=scope, db=db)
    if reason_code is not None:
        return _decision(
            actor=actor,
            permission=permission,
            target=target,
            allowed=True,
            reason_code=reason_code,
        )
    return _decision(
        actor=actor,
        permission=permission,
        target=target,
        allowed=False,
        reason_code="missing_permission",
    )


async def require(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    scope: Scope,
    db: AsyncSession,
) -> AuthorizationDecision:
    decision = await can(actor=actor, permission=permission, target=target, scope=scope, db=db)
    if not decision.allowed:
        raise AuthorizationDeniedError(decision)
    return decision


async def can_manage_assignment_scope(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    scope: Scope,
    db: AsyncSession,
) -> AuthorizationDecision:
    grant = _grant_decision(actor=actor, permission=permission, target=target)
    if grant is not None:
        return grant
    if target.scope_type == "org":
        return _decision(
            actor=actor,
            permission=permission,
            target=target,
            allowed=False,
            reason_code="missing_permission",
        )
    reason_code = await _scoped_workspace_reason(actor=actor, target=target, scope=scope, db=db)
    if reason_code is not None:
        return _decision(
            actor=actor,
            permission=permission,
            target=target,
            allowed=True,
            reason_code=reason_code,
        )
    return _decision(
        actor=actor,
        permission=permission,
        target=target,
        allowed=False,
        reason_code="missing_permission",
    )


def _grant_decision(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
) -> AuthorizationDecision | None:
    permissions = _effective_permissions(actor)
    if Permissions.WILDCARD in permissions:
        return _decision(
            actor=actor,
            permission=permission,
            target=target,
            allowed=True,
            reason_code="wildcard_grant",
            matched_permission=Permissions.WILDCARD,
        )
    if permission in permissions:
        return _decision(
            actor=actor,
            permission=permission,
            target=target,
            allowed=True,
            reason_code="permission_grant",
            matched_permission=permission,
        )
    return None


def _member_grant_decision(
    *,
    actor: AuthenticatedUser,
    permission: str,
) -> AuthorizationDecision | None:
    permissions = _effective_permissions(actor)
    if Permissions.WILDCARD in permissions:
        return _member_decision(
            actor=actor,
            permission=permission,
            reason_code="wildcard_grant",
            allowed=True,
            matched_permission=Permissions.WILDCARD,
        )
    if permission in permissions:
        return _member_decision(
            actor=actor,
            permission=permission,
            reason_code="permission_grant",
            allowed=True,
            matched_permission=permission,
        )
    return None


def _scoped_invite_decision(
    *,
    actor: AuthenticatedUser,
    target: MemberInviteTarget,
    creating: bool,
) -> AuthorizationDecision:
    if target.team_id and target.team_id in _team_admin_ids(actor):
        if target.project_team_id is not None and target.project_team_id != target.team_id:
            return _invalid_invite_scope(actor)
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="scoped_team_admin",
            allowed=True,
        )
    if target.project_team_id is not None and target.project_team_id in _team_admin_ids(actor):
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="scoped_team_admin",
            allowed=True,
        )
    if target.project_id is not None and target.project_id in _project_admin_ids(actor):
        if target.team_id is not None or target.team_role is not None:
            return _invalid_invite_scope(actor)
        if creating and target.project_role not in {"project_admin", "project_member"}:
            return _invalid_invite_scope(actor)
        return _member_decision(
            actor=actor,
            permission=Permissions.MEMBERS_MANAGE,
            reason_code="scoped_project_admin",
            allowed=True,
        )
    return _member_decision(
        actor=actor,
        permission=Permissions.MEMBERS_MANAGE,
        reason_code="missing_permission",
        allowed=False,
    )


def _invalid_invite_scope(actor: AuthenticatedUser) -> AuthorizationDecision:
    return _member_decision(
        actor=actor,
        permission=Permissions.MEMBERS_MANAGE,
        reason_code="invalid_invite_scope",
        allowed=False,
    )


async def _scoped_workspace_reason(
    *,
    actor: AuthenticatedUser,
    target: AuthorizationTarget,
    scope: Scope,
    db: AsyncSession,
) -> str | None:
    if target.scope_type == "team":
        if target.team_id is None:
            return None
        team = await workspace_facade.get_team_identity(team_id=target.team_id, scope=scope, db=db)
        if team is None:
            return None
        if target.relationship == "member":
            if await auth_facade.has_team_membership(
                org_id=actor.org_id,
                team_id=target.team_id,
                user_id=actor.id,
                db=db,
            ):
                return "scoped_team_admin"
            return None
        team_ids = _team_admin_ids(actor)
        return "scoped_team_admin" if target.team_id in team_ids else None
    if target.scope_type == "project":
        if target.project_id is None:
            return None
        project = await workspace_facade.get_project_identity(
            project_id=target.project_id,
            scope=scope,
            db=db,
        )
        if project is None:
            return None
        if target.relationship == "member":
            if await auth_facade.has_project_membership(
                org_id=actor.org_id,
                project_id=project.id,
                user_id=actor.id,
                db=db,
            ) or await auth_facade.has_team_membership(
                org_id=actor.org_id,
                team_id=project.team_id,
                user_id=actor.id,
                db=db,
            ):
                return "scoped_project_admin"
            return None
        return _project_scope_reason(
            team_id=project.team_id,
            project_id=project.id,
            team_admin_ids=_team_admin_ids(actor),
            project_admin_ids=_project_admin_ids(actor),
        )
    if target.scope_type == "virtual_key":
        if target.virtual_key_id is None:
            return None
        virtual_key = await workspace_facade.get_virtual_key_identity(
            virtual_key_id=target.virtual_key_id,
            scope=scope,
            db=db,
        )
        if virtual_key is None:
            return None
        project = await workspace_facade.get_project_identity(
            project_id=virtual_key.project_id,
            scope=scope,
            db=db,
        )
        if project is None:
            return None
        if target.relationship == "member":
            if await auth_facade.has_project_membership(
                org_id=actor.org_id,
                project_id=project.id,
                user_id=actor.id,
                db=db,
            ) or await auth_facade.has_team_membership(
                org_id=actor.org_id,
                team_id=project.team_id,
                user_id=actor.id,
                db=db,
            ):
                return "scoped_project_admin"
            return None
        return _project_scope_reason(
            team_id=project.team_id,
            project_id=project.id,
            team_admin_ids=_team_admin_ids(actor),
            project_admin_ids=_project_admin_ids(actor),
        )
    return None


def _project_scope_reason(
    *,
    team_id: UUID,
    project_id: UUID,
    team_admin_ids: set[UUID],
    project_admin_ids: set[UUID],
) -> str | None:
    if project_id in project_admin_ids:
        return "scoped_project_admin"
    if team_id in team_admin_ids:
        return "scoped_team_admin"
    return None


def _team_admin_ids(actor: AuthenticatedUser) -> set[UUID]:
    return {
        membership.team_id
        for membership in actor.team_memberships
        if membership.role == "team_admin"
    }


def _team_member_ids(actor: AuthenticatedUser) -> set[UUID]:
    return {membership.team_id for membership in actor.team_memberships}


def _project_admin_ids(actor: AuthenticatedUser) -> set[UUID]:
    return {
        membership.project_id
        for membership in actor.project_memberships
        if membership.role == "project_admin"
    }


def _project_member_ids(actor: AuthenticatedUser) -> set[UUID]:
    return {membership.project_id for membership in actor.project_memberships}


def _effective_permissions(actor: AuthenticatedUser) -> set[str]:
    permissions = set(actor.permissions)
    permissions.update(ROLE_PERMISSIONS.get(actor.role, set()))
    return permissions


def _decision(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    allowed: bool,
    reason_code: str,
    matched_permission: str | None = None,
) -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=allowed,
        permission=permission,
        target_kind=target.kind,
        reason_code=reason_code,
        matched_permission=matched_permission,
        matched_role=actor.role if allowed else None,
        scope_type=target.scope_type,
    )


def _member_decision(
    *,
    actor: AuthenticatedUser,
    permission: str,
    reason_code: str,
    allowed: bool,
    matched_permission: str | None = None,
) -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=allowed,
        permission=permission,
        target_kind="member_management",
        reason_code=reason_code,
        matched_permission=matched_permission,
        matched_role=actor.role if allowed else None,
    )
