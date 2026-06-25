from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.authorization import service
from app.modules.authorization.schemas import (
    AuthorizationDecision,
    AuthorizationTarget,
    AuthorizedWorkspaceScopes,
    MemberInviteTarget,
    MemberRoleChangeTarget,
    MemberStatusChangeTarget,
    ScopedMembershipTarget,
)


def has_permission(actor: AuthenticatedUser, permission: str) -> bool:
    return service.has_permission(actor, permission)


def has_any_permission(actor: AuthenticatedUser, permissions: set[str]) -> bool:
    return service.has_any_permission(actor, permissions)


def has_any_role(actor: AuthenticatedUser, roles: set[str]) -> bool:
    return service.has_any_role(actor, roles)


def authorized_workspace_ids(
    actor: AuthenticatedUser,
    *,
    relationship: str,
) -> AuthorizedWorkspaceScopes:
    return service.authorized_workspace_ids(actor, relationship=relationship)


def scoped_admin_workspace_ids(actor: AuthenticatedUser) -> AuthorizedWorkspaceScopes:
    return service.scoped_admin_workspace_ids(actor)


def can_manage_org_role(
    *,
    actor: AuthenticatedUser,
    target: MemberRoleChangeTarget,
) -> AuthorizationDecision:
    return service.can_manage_org_role(actor=actor, target=target)


def can_change_member_status(
    *,
    actor: AuthenticatedUser,
    target: MemberStatusChangeTarget,
) -> AuthorizationDecision:
    return service.can_change_member_status(actor=actor, target=target)


def can_change_member_role_without_self_demotion(
    *,
    actor: AuthenticatedUser,
    target: MemberRoleChangeTarget,
) -> AuthorizationDecision:
    return service.can_change_member_role_without_self_demotion(actor=actor, target=target)


def can_create_member_invite(
    *,
    actor: AuthenticatedUser,
    target: MemberInviteTarget,
) -> AuthorizationDecision:
    return service.can_create_member_invite(actor=actor, target=target)


def can_manage_member_invite(
    *,
    actor: AuthenticatedUser,
    target: MemberInviteTarget,
) -> AuthorizationDecision:
    return service.can_manage_member_invite(actor=actor, target=target)


def can_manage_scoped_membership(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: ScopedMembershipTarget,
) -> AuthorizationDecision:
    return service.can_manage_scoped_membership(
        actor=actor,
        permission=permission,
        target=target,
    )


def effective_permissions_for_member(
    *,
    org_role: str,
    team_roles: list[str],
    project_roles: list[str],
) -> list[str]:
    return service.effective_permissions_for_member(
        org_role=org_role,
        team_roles=team_roles,
        project_roles=project_roles,
    )


async def can(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    scope: Scope,
    db: AsyncSession,
) -> AuthorizationDecision:
    return await service.can(
        actor=actor,
        permission=permission,
        target=target,
        scope=scope,
        db=db,
    )


async def require(
    *,
    actor: AuthenticatedUser,
    permission: str,
    target: AuthorizationTarget,
    scope: Scope,
    db: AsyncSession,
) -> AuthorizationDecision:
    return await service.require(
        actor=actor,
        permission=permission,
        target=target,
        scope=scope,
        db=db,
    )
