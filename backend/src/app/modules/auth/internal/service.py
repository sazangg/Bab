import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import Scope, transaction
from app.core.security import (
    SecurityError,
    create_access_token,
    decode_access_token,
    generate_secret_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.activity.metadata import sanitize_metadata
from app.modules.auth.errors import (
    DuplicateInviteError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidInviteTargetError,
    InvalidRefreshTokenError,
    InviteLifecycleError,
    InviteNotFoundError,
    LastOwnerError,
    MemberAlreadyExistsError,
    MemberNotFoundError,
    MemberOrganizationConflictError,
    PermissionDeniedError,
    RefreshTokenReuseError,
)
from app.modules.auth.internal.models import (
    AuditEvent,
    AuditLedgerState,
    IdentityAccount,
    Invite,
    Organization,
    OrganizationMembership,
    ProjectMembership,
    Team,
    TeamMembership,
    User,
)
from app.modules.auth.internal.refresh_sessions import (
    create_refresh_session,
    revoke_refresh_session,
    revoke_refresh_session_family,
    rotate_refresh_session,
)
from app.modules.auth.schemas import (
    AcceptInviteRequest,
    AuditEventResponse,
    AuthenticatedProjectMembership,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
    CreateInviteRequest,
    CreateMemberRequest,
    InvitePreviewResponse,
    InviteResponse,
    LoginRequest,
    MemberOptionResponse,
    MemberProjectMembershipResponse,
    MemberResponse,
    MemberTeamMembershipResponse,
    ProjectMemberResponse,
    TeamMemberResponse,
    TokenResponse,
    UpdateMemberRequest,
    UpdateMemberStatusRequest,
    UpdateProjectMemberRequest,
    UpdateTeamMemberRequest,
    UpsertProjectMemberRequest,
    UpsertTeamMemberRequest,
)
from app.modules.keys.internal.models import Project

MOCK_ADMIN_ID = UUID("00000000-0000-4000-8000-000000000001")
INVITE_TOKEN_TTL = timedelta(days=7)

ROLE_PERMISSIONS = {
    "org_owner": {"*"},
    "org_admin": {
        "providers.manage",
        "providers.view",
        "policies.manage",
        "policies.view",
        "teams.manage",
        "teams.view",
        "projects.manage",
        "projects.view",
        "keys.manage",
        "usage.view",
        "activity.view",
        "settings.manage",
        "settings.view",
        "guardrails.manage",
        "guardrails.view",
        "members.manage",
        "audit.view",
    },
    "org_viewer": {
        "providers.view",
        "policies.view",
        "teams.view",
        "projects.view",
        "usage.view",
        "activity.view",
        "settings.view",
        "guardrails.view",
    },
    "org_member": set(),
}


async def login(payload: LoginRequest, db: AsyncSession) -> tuple[TokenResponse, str]:
    async with transaction(db):
        user = await db.scalar(select(User).where(User.email == str(payload.email).lower()))
        if user is None or not user.is_active or not user.password_hash:
            raise InvalidCredentialsError
        try:
            password_is_valid = verify_password(payload.password, user.password_hash)
        except SecurityError as exc:
            raise InvalidCredentialsError from exc
        if not password_is_valid:
            raise InvalidCredentialsError

        try:
            principal = await _principal_for_user(user.id, db)
        except InvalidAccessTokenError as exc:
            # No active organization membership (e.g. deactivated member).
            raise InvalidCredentialsError from exc
        raw_refresh_token = await create_refresh_session(
            user_id=principal.id,
            org_id=principal.org_id,
            db=db,
        )
    return _access_response(principal), raw_refresh_token


async def refresh(raw_refresh_token: str | None, db: AsyncSession) -> tuple[TokenResponse, str]:
    try:
        async with transaction(db):
            session, new_raw_refresh_token = await rotate_refresh_session(
                raw_token=raw_refresh_token,
                db=db,
            )
            try:
                principal = await _principal_for_user(session.user_id, db)
            except InvalidAccessTokenError as exc:
                raise InvalidRefreshTokenError from exc
    except RefreshTokenReuseError as exc:
        # Replay of an already-rotated token: revoke the whole rotation chain in a
        # fresh (committed) transaction, then reject.
        async with transaction(db):
            await revoke_refresh_session_family(raw_token=raw_refresh_token, db=db)
        raise InvalidRefreshTokenError from exc
    return _access_response(principal), new_raw_refresh_token


async def logout(raw_refresh_token: str | None, db: AsyncSession) -> None:
    async with transaction(db):
        session = await revoke_refresh_session(raw_token=raw_refresh_token, db=db)
        if session is None:
            return
        try:
            actor = await _principal_for_user(session.user_id, db)
        except InvalidAccessTokenError:
            return
        await record_audit_event(
            actor=actor,
            action="refresh_session.revoked",
            entity_type="refresh_session",
            entity_id=session.id,
            metadata={"user_id": str(session.user_id), "reason": "logout"},
            db=db,
        )


async def verify_access_token(token: str, db: AsyncSession) -> AuthenticatedUser:
    try:
        claims = decode_access_token(token)
        user_id = UUID(str(claims.get("sub")))
        org_id = UUID(str(claims.get("org_id")))
    except (SecurityError, ValueError, TypeError) as exc:
        raise InvalidAccessTokenError from exc

    # Bind the principal to the organization the token was issued for instead of
    # re-deriving it; the org context must come from the signed claim, not a guess.
    return await _principal_for_user(user_id, db, org_id=org_id)


async def list_members(*, scope: Scope, db: AsyncSession) -> list[MemberResponse]:
    rows = await db.execute(
        select(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(OrganizationMembership.org_id == scope.org_id)
        .order_by(User.email)
    )
    memberships_by_user = await _scoped_memberships_by_user(scope=scope, db=db)
    members = []
    for user, membership in rows:
        team_memberships, project_memberships = memberships_by_user.get(user.id, ([], []))
        members.append(
            MemberResponse(
                user_id=user.id,
                email=user.email,
                name=user.name,
                role=membership.role,
                status=membership.status,
                created_at=membership.created_at,
                team_memberships=[
                    MemberTeamMembershipResponse(team_id=item.team_id, role=item.role)
                    for item in team_memberships
                ],
                project_memberships=[
                    MemberProjectMembershipResponse(project_id=item.project_id, role=item.role)
                    for item in project_memberships
                ],
                effective_permissions=_effective_permissions_for_memberships(
                    org_role=membership.role,
                    team_memberships=team_memberships,
                    project_memberships=project_memberships,
                ),
            )
        )
    return members


async def list_member_options(*, scope: Scope, db: AsyncSession) -> list[MemberOptionResponse]:
    users = await db.scalars(
        select(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            OrganizationMembership.org_id == scope.org_id,
            OrganizationMembership.status == "active",
            User.is_active.is_(True),
        )
        .order_by(User.email)
    )
    return [
        MemberOptionResponse(user_id=user.id, email=user.email, name=user.name) for user in users
    ]


async def create_member(
    *,
    payload: CreateMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> MemberResponse:
    email = str(payload.email).lower()
    async with transaction(db):
        team, project = await _validate_scoped_target(payload=payload, scope=scope, db=db)
        _ensure_actor_can_manage_org_role(actor=actor, current_role=None, new_role=payload.role)
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            raise MemberAlreadyExistsError
        user = User(
            email=email,
            name=payload.name,
            password_hash=hash_password(payload.password),
            is_active=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            IdentityAccount(
                user_id=user.id,
                provider="local",
                provider_subject=user.email,
                email=user.email,
            )
        )
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == scope.org_id,
                OrganizationMembership.user_id == user.id,
            )
        )
        previous_role = membership.role if membership else None
        previous_status = membership.status if membership else None
        if membership is None:
            membership = OrganizationMembership(
                org_id=scope.org_id,
                user_id=user.id,
                role=payload.role,
                status="active",
            )
            db.add(membership)
        else:
            _ensure_actor_can_manage_org_role(
                actor=actor,
                current_role=membership.role,
                new_role=payload.role,
            )
            membership.role = payload.role
            membership.status = "active"
        if team and payload.team_role:
            team_membership = await db.scalar(
                select(TeamMembership).where(
                    TeamMembership.org_id == scope.org_id,
                    TeamMembership.team_id == team.id,
                    TeamMembership.user_id == user.id,
                )
            )
            if team_membership is None:
                db.add(
                    TeamMembership(
                        org_id=scope.org_id,
                        team_id=team.id,
                        user_id=user.id,
                        role=payload.team_role,
                    )
                )
            else:
                team_membership.role = payload.team_role
        if project and payload.project_role:
            project_membership = await db.scalar(
                select(ProjectMembership).where(
                    ProjectMembership.org_id == scope.org_id,
                    ProjectMembership.project_id == project.id,
                    ProjectMembership.user_id == user.id,
                )
            )
            if project_membership is None:
                db.add(
                    ProjectMembership(
                        org_id=scope.org_id,
                        project_id=project.id,
                        user_id=user.id,
                        role=payload.project_role,
                    )
                )
            else:
                project_membership.role = payload.project_role
        await db.flush()
        await record_audit_event(
            actor=actor,
            action="member.created",
            entity_type="user",
            entity_id=user.id,
            metadata={
                "email": email,
                "previous_role": previous_role,
                "role": payload.role,
                "previous_status": previous_status,
                "status": "active",
                "team_id": str(team.id) if team else None,
                "team_role": payload.team_role,
                "project_id": str(project.id) if project else None,
                "project_role": payload.project_role,
            },
            db=db,
        )
    members = await list_members(scope=scope, db=db)
    return next(member for member in members if member.user_id == user.id)


async def update_member(
    *,
    user_id: UUID,
    payload: UpdateMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> MemberResponse:
    async with transaction(db):
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == scope.org_id,
                OrganizationMembership.user_id == user_id,
            )
        )
        if membership is None:
            raise MemberNotFoundError
        _ensure_actor_can_manage_org_role(
            actor=actor,
            current_role=membership.role,
            new_role=payload.role,
        )
        previous_role = membership.role
        if previous_role == "org_owner" and payload.role != "org_owner":
            await _ensure_not_last_owner(scope=scope, excluding_user_id=user_id, db=db)
        _ensure_not_self_demoting_member_admin(
            actor=actor,
            user_id=user_id,
            current_role=previous_role,
            new_role=payload.role,
        )
        membership.role = payload.role
        await db.flush()
        await record_audit_event(
            actor=actor,
            action="member.role_updated",
            entity_type="user",
            entity_id=user_id,
            metadata={"previous_role": previous_role, "role": payload.role},
            db=db,
        )
    members = await list_members(scope=scope, db=db)
    return next(member for member in members if member.user_id == user_id)


async def update_member_status(
    *,
    user_id: UUID,
    payload: UpdateMemberStatusRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> MemberResponse:
    async with transaction(db):
        row = (
            await db.execute(
                select(User, OrganizationMembership)
                .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
                .where(
                    OrganizationMembership.org_id == scope.org_id,
                    User.id == user_id,
                )
            )
        ).first()
        if row is None:
            raise MemberNotFoundError
        user, membership = row
        _ensure_actor_can_manage_org_role(
            actor=actor,
            current_role=membership.role,
            new_role=membership.role,
        )
        # Activation is gated per organization via membership.status, NOT the global
        # User.is_active flag. Toggling the shared user row here would let one org's
        # admin lock the user out of (or re-enable them in) another org.
        del user
        if payload.status == "inactive":
            if membership.role == "org_owner":
                await _ensure_not_last_owner(scope=scope, excluding_user_id=user_id, db=db)
            _ensure_not_self_deactivating(actor=actor, user_id=user_id)
            previous_status = membership.status
            membership.status = "inactive"
        else:
            previous_status = membership.status
            membership.status = "active"
        await db.flush()
        await record_audit_event(
            actor=actor,
            action="member.status_updated",
            entity_type="user",
            entity_id=user_id,
            metadata={"previous_status": previous_status, "status": payload.status},
            db=db,
        )
    members = await list_members(scope=scope, db=db)
    return next(member for member in members if member.user_id == user_id)


async def _ensure_not_last_owner(
    *, scope: Scope, excluding_user_id: UUID, db: AsyncSession
) -> None:
    remaining_owner = await db.scalar(
        select(OrganizationMembership.id).where(
            OrganizationMembership.org_id == scope.org_id,
            OrganizationMembership.user_id != excluding_user_id,
            OrganizationMembership.role == "org_owner",
            OrganizationMembership.status == "active",
        )
    )
    if remaining_owner is None:
        raise LastOwnerError


def _ensure_actor_can_manage_org_role(
    *,
    actor: AuthenticatedUser,
    current_role: str | None,
    new_role: str,
) -> None:
    if actor.role == "org_owner" or "*" in actor.permissions:
        return
    if actor.role != "org_admin":
        raise PermissionDeniedError
    if current_role in {"org_owner", "org_admin"} or new_role in {"org_owner", "org_admin"}:
        raise PermissionDeniedError


def _ensure_not_self_demoting_member_admin(
    *,
    actor: AuthenticatedUser,
    user_id: UUID,
    current_role: str,
    new_role: str,
) -> None:
    if actor.id != user_id or current_role == new_role:
        return
    if has_permission(actor, "members.manage") and new_role not in {"org_owner", "org_admin"}:
        raise PermissionDeniedError


def _ensure_not_self_deactivating(*, actor: AuthenticatedUser, user_id: UUID) -> None:
    if actor.id == user_id and has_permission(actor, "members.manage"):
        raise PermissionDeniedError


async def _scoped_memberships_by_user(
    *,
    scope: Scope,
    db: AsyncSession,
) -> dict[UUID, tuple[list[TeamMembership], list[ProjectMembership]]]:
    team_rows = list(
        await db.scalars(select(TeamMembership).where(TeamMembership.org_id == scope.org_id))
    )
    project_rows = list(
        await db.scalars(select(ProjectMembership).where(ProjectMembership.org_id == scope.org_id))
    )
    memberships: dict[UUID, tuple[list[TeamMembership], list[ProjectMembership]]] = {}
    for item in team_rows:
        teams, projects = memberships.setdefault(item.user_id, ([], []))
        teams.append(item)
    for item in project_rows:
        teams, projects = memberships.setdefault(item.user_id, ([], []))
        projects.append(item)
    return memberships


def _effective_permissions_for_memberships(
    *,
    org_role: str,
    team_memberships: list[TeamMembership],
    project_memberships: list[ProjectMembership],
) -> list[str]:
    permissions = set(ROLE_PERMISSIONS.get(org_role, set()))
    if any(item.role == "team_admin" for item in team_memberships):
        permissions.update(
            {
                "keys.manage",
                "policies.view",
                "guardrails.view",
                "projects.view",
                "teams.view",
            }
        )
    if any(item.role == "project_admin" for item in project_memberships):
        permissions.update({"keys.manage", "policies.view", "guardrails.view", "projects.view"})
    return sorted(permissions)


async def list_team_members(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> list[TeamMemberResponse]:
    await _require_team(team_id=team_id, scope=scope, db=db)
    rows = await db.execute(
        select(User, OrganizationMembership, TeamMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(
            OrganizationMembership.org_id == scope.org_id,
            OrganizationMembership.status == "active",
            TeamMembership.org_id == scope.org_id,
            TeamMembership.team_id == team_id,
        )
        .order_by(User.email)
    )
    return [
        TeamMemberResponse(
            user_id=user.id,
            email=user.email,
            name=user.name,
            org_role=org_membership.role,
            team_role=team_membership.role,
            created_at=team_membership.created_at,
        )
        for user, org_membership, team_membership in rows
    ]


async def upsert_team_member(
    *,
    team_id: UUID,
    payload: UpsertTeamMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamMemberResponse:
    async with transaction(db):
        await _require_team(team_id=team_id, scope=scope, db=db)
        _ensure_actor_can_manage_team_members(actor=actor, team_id=team_id)
        org_membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == scope.org_id,
                OrganizationMembership.user_id == payload.user_id,
                OrganizationMembership.status == "active",
            )
        )
        if org_membership is None:
            raise InvalidAccessTokenError
        team_membership = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.org_id == scope.org_id,
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == payload.user_id,
            )
        )
        action = "team_member.added"
        previous_role = None
        if team_membership is None:
            team_membership = TeamMembership(
                org_id=scope.org_id,
                team_id=team_id,
                user_id=payload.user_id,
                role=payload.role,
            )
            db.add(team_membership)
        else:
            action = "team_member.role_updated"
            previous_role = team_membership.role
            team_membership.role = payload.role
        await db.flush()
        await record_audit_event(
            actor=actor,
            action=action,
            entity_type="team_member",
            entity_id=team_membership.id,
            metadata={
                "team_id": str(team_id),
                "user_id": str(payload.user_id),
                "previous_role": previous_role,
                "role": payload.role,
            },
            db=db,
        )
    members = await list_team_members(team_id=team_id, scope=scope, db=db)
    return next(member for member in members if member.user_id == payload.user_id)


async def update_team_member(
    *,
    team_id: UUID,
    user_id: UUID,
    payload: UpdateTeamMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamMemberResponse:
    return await upsert_team_member(
        team_id=team_id,
        payload=UpsertTeamMemberRequest(user_id=user_id, role=payload.role),
        actor=actor,
        scope=scope,
        db=db,
    )


async def remove_team_member(
    *,
    team_id: UUID,
    user_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        await _require_team(team_id=team_id, scope=scope, db=db)
        _ensure_actor_can_manage_team_members(actor=actor, team_id=team_id)
        team_membership = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.org_id == scope.org_id,
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id,
            )
        )
        if team_membership is None:
            raise MemberNotFoundError
        await db.delete(team_membership)
        await record_audit_event(
            actor=actor,
            action="team_member.removed",
            entity_type="team_member",
            entity_id=team_membership.id,
            metadata={
                "team_id": str(team_id),
                "user_id": str(user_id),
                "previous_role": team_membership.role,
            },
            db=db,
        )


async def list_project_members(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> list[ProjectMemberResponse]:
    await _require_project(project_id=project_id, scope=scope, db=db)
    rows = await db.execute(
        select(User, OrganizationMembership, ProjectMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .join(ProjectMembership, ProjectMembership.user_id == User.id)
        .where(
            OrganizationMembership.org_id == scope.org_id,
            OrganizationMembership.status == "active",
            ProjectMembership.org_id == scope.org_id,
            ProjectMembership.project_id == project_id,
        )
        .order_by(User.email)
    )
    return [
        ProjectMemberResponse(
            user_id=user.id,
            email=user.email,
            name=user.name,
            org_role=org_membership.role,
            project_role=project_membership.role,
            created_at=project_membership.created_at,
        )
        for user, org_membership, project_membership in rows
    ]


async def upsert_project_member(
    *,
    project_id: UUID,
    payload: UpsertProjectMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectMemberResponse:
    async with transaction(db):
        project = await _require_project(project_id=project_id, scope=scope, db=db)
        _ensure_actor_can_manage_project_members(actor=actor, project=project)
        org_membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == scope.org_id,
                OrganizationMembership.user_id == payload.user_id,
                OrganizationMembership.status == "active",
            )
        )
        if org_membership is None:
            raise InvalidAccessTokenError
        project_membership = await db.scalar(
            select(ProjectMembership).where(
                ProjectMembership.org_id == scope.org_id,
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == payload.user_id,
            )
        )
        action = "project_member.added"
        previous_role = None
        if project_membership is None:
            project_membership = ProjectMembership(
                org_id=scope.org_id,
                project_id=project_id,
                user_id=payload.user_id,
                role=payload.role,
            )
            db.add(project_membership)
        else:
            action = "project_member.role_updated"
            previous_role = project_membership.role
            project_membership.role = payload.role
        await db.flush()
        await record_audit_event(
            actor=actor,
            action=action,
            entity_type="project_member",
            entity_id=project_membership.id,
            metadata={
                "project_id": str(project_id),
                "user_id": str(payload.user_id),
                "previous_role": previous_role,
                "role": payload.role,
            },
            db=db,
        )
    members = await list_project_members(project_id=project_id, scope=scope, db=db)
    return next(member for member in members if member.user_id == payload.user_id)


async def update_project_member(
    *,
    project_id: UUID,
    user_id: UUID,
    payload: UpdateProjectMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectMemberResponse:
    return await upsert_project_member(
        project_id=project_id,
        payload=UpsertProjectMemberRequest(user_id=user_id, role=payload.role),
        actor=actor,
        scope=scope,
        db=db,
    )


async def remove_project_member(
    *,
    project_id: UUID,
    user_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        project = await _require_project(project_id=project_id, scope=scope, db=db)
        _ensure_actor_can_manage_project_members(actor=actor, project=project)
        project_membership = await db.scalar(
            select(ProjectMembership).where(
                ProjectMembership.org_id == scope.org_id,
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
            )
        )
        if project_membership is None:
            raise MemberNotFoundError
        await db.delete(project_membership)
        await record_audit_event(
            actor=actor,
            action="project_member.removed",
            entity_type="project_member",
            entity_id=project_membership.id,
            metadata={
                "project_id": str(project_id),
                "user_id": str(user_id),
                "previous_role": project_membership.role,
            },
            db=db,
        )


async def create_invite(
    *,
    payload: CreateInviteRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    public_base_url: str | None,
    db: AsyncSession,
) -> InviteResponse:
    raw_token = generate_secret_token()
    async with transaction(db):
        team, project = await _validate_invite_target(payload=payload, scope=scope, db=db)
        _ensure_actor_can_create_invite(
            actor=actor,
            role=payload.role,
            team_id=payload.team_id,
            team_role=payload.team_role,
            project=project,
            project_role=payload.project_role,
        )
        await _ensure_no_duplicate_pending_invite(
            org_id=scope.org_id,
            email=str(payload.email).lower(),
            team_id=payload.team_id,
            project_id=payload.project_id,
            db=db,
        )
        invite = Invite(
            org_id=scope.org_id,
            team_id=payload.team_id,
            project_id=payload.project_id,
            email=str(payload.email).lower(),
            role=payload.role,
            team_role=payload.team_role,
            project_role=payload.project_role,
            token_hash=hash_token(raw_token),
            invited_by_user_id=actor.id,
            expires_at=datetime.now(UTC) + INVITE_TOKEN_TTL,
        )
        db.add(invite)
        await db.flush()
        await record_audit_event(
            actor=actor,
            action="invite.created",
            entity_type="invite",
            entity_id=invite.id,
            metadata={
                "email": invite.email,
                "role": invite.role,
                "team_id": str(team.id) if team else None,
                "team_role": invite.team_role,
                "project_id": str(project.id) if project else None,
                "project_role": invite.project_role,
            },
            db=db,
        )
    return _invite_response(invite, raw_token=raw_token, public_base_url=public_base_url)


async def list_invites(
    *,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> list[InviteResponse]:
    invites = await db.scalars(
        select(Invite).where(Invite.org_id == scope.org_id).order_by(Invite.created_at.desc())
    )
    project_team_by_id = await _project_team_by_id(scope=scope, db=db)
    return [
        _invite_response(invite, raw_token=None, public_base_url=None)
        for invite in invites
        if _actor_can_manage_invite(
            actor=actor,
            invite=invite,
            project_team_id=project_team_by_id.get(invite.project_id),
        )
    ]


async def preview_invite(*, token: str, db: AsyncSession) -> InvitePreviewResponse:
    invite = await db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None:
        raise InviteNotFoundError
    organization = await db.scalar(select(Organization).where(Organization.id == invite.org_id))
    team = (
        await db.scalar(select(Team).where(Team.id == invite.team_id)) if invite.team_id else None
    )
    project = (
        await db.scalar(select(Project).where(Project.id == invite.project_id))
        if invite.project_id
        else None
    )
    status = (
        "expired" if invite.status == "pending" and _is_past(invite.expires_at) else invite.status
    )
    return InvitePreviewResponse(
        email=invite.email,
        organization_name=organization.name if organization else "Organization",
        role=invite.role,
        team_name=team.name if team else None,
        team_role=invite.team_role,
        project_name=project.name if project else None,
        project_role=invite.project_role,
        status=status,
        expires_at=invite.expires_at,
    )


async def _validate_invite_target(
    *,
    payload: CreateInviteRequest,
    scope: Scope,
    db: AsyncSession,
) -> tuple[Team | None, Project | None]:
    return await _validate_scoped_target(payload=payload, scope=scope, db=db)


async def _validate_scoped_target(
    *,
    payload: CreateInviteRequest | CreateMemberRequest,
    scope: Scope,
    db: AsyncSession,
) -> tuple[Team | None, Project | None]:
    if payload.team_role and payload.team_id is None:
        raise InvalidInviteTargetError
    if payload.project_role and payload.project_id is None:
        raise InvalidInviteTargetError
    if payload.project_id and payload.project_role is None:
        raise InvalidInviteTargetError

    team = None
    if payload.team_id:
        team = await db.scalar(
            select(Team).where(
                Team.id == payload.team_id,
                Team.org_id == scope.org_id,
                Team.is_active.is_(True),
            )
        )
        if team is None:
            raise InvalidInviteTargetError

    project = None
    if payload.project_id:
        project = await db.scalar(
            select(Project).where(
                Project.id == payload.project_id,
                Project.org_id == scope.org_id,
                Project.is_active.is_(True),
            )
        )
        if project is None:
            raise InvalidInviteTargetError
        if payload.team_id and project.team_id != payload.team_id:
            raise InvalidInviteTargetError

    return team, project


async def _ensure_no_duplicate_pending_invite(
    *,
    org_id: UUID,
    email: str,
    team_id: UUID | None,
    project_id: UUID | None,
    db: AsyncSession,
) -> None:
    pending_invites = await db.scalars(
        select(Invite).where(
            Invite.org_id == org_id,
            Invite.email == email,
            Invite.status == "pending",
        )
    )
    for invite in pending_invites:
        if _is_past(invite.expires_at):
            continue
        if invite.team_id == team_id and invite.project_id == project_id:
            raise DuplicateInviteError


def _ensure_actor_can_create_invite(
    *,
    actor: AuthenticatedUser,
    role: str,
    team_id: UUID | None,
    team_role: str | None,
    project: Project | None,
    project_role: str | None,
) -> None:
    if has_permission(actor, "members.manage"):
        _ensure_actor_can_manage_org_role(actor=actor, current_role=None, new_role=role)
        return

    if role != "org_member":
        raise PermissionDeniedError

    if team_id and _is_team_admin_actor(actor=actor, team_id=team_id):
        if project and project.team_id != team_id:
            raise PermissionDeniedError
        return

    if project and _is_team_admin_actor(actor=actor, team_id=project.team_id):
        return

    if project and _is_project_admin_actor(actor=actor, project_id=project.id):
        if team_id or team_role:
            raise PermissionDeniedError
        if project_role not in {"project_admin", "project_member"}:
            raise PermissionDeniedError
        return

    raise PermissionDeniedError


def _is_team_admin_actor(*, actor: AuthenticatedUser, team_id: UUID) -> bool:
    return any(
        item.team_id == team_id and item.role == "team_admin" for item in actor.team_memberships
    )


def _is_project_admin_actor(*, actor: AuthenticatedUser, project_id: UUID) -> bool:
    return any(
        item.project_id == project_id and item.role == "project_admin"
        for item in actor.project_memberships
    )


async def _project_team_by_id(*, scope: Scope, db: AsyncSession) -> dict[UUID, UUID]:
    rows = await db.execute(
        select(Project.id, Project.team_id).where(Project.org_id == scope.org_id)
    )
    return {project_id: team_id for project_id, team_id in rows if team_id is not None}


def _actor_can_manage_invite(
    *,
    actor: AuthenticatedUser,
    invite: Invite,
    project_team_id: UUID | None,
) -> bool:
    if has_permission(actor, "members.manage"):
        return True
    if invite.team_id and _is_team_admin_actor(actor=actor, team_id=invite.team_id):
        return True
    if project_team_id and _is_team_admin_actor(actor=actor, team_id=project_team_id):
        return True
    if (
        invite.project_id
        and invite.team_id is None
        and _is_project_admin_actor(actor=actor, project_id=invite.project_id)
    ):
        return True
    return False


async def revoke_invite(
    *,
    invite_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    async with transaction(db):
        invite = await db.scalar(
            select(Invite).where(Invite.id == invite_id, Invite.org_id == scope.org_id)
        )
        if invite is None:
            raise InviteNotFoundError
        project_team_id = None
        if invite.project_id:
            project_team_id = await db.scalar(
                select(Project.team_id).where(
                    Project.id == invite.project_id,
                    Project.org_id == scope.org_id,
                )
            )
        if not _actor_can_manage_invite(
            actor=actor,
            invite=invite,
            project_team_id=project_team_id,
        ):
            raise PermissionDeniedError
        if invite.status != "pending" or _is_past(invite.expires_at):
            raise InviteLifecycleError
        invite.status = "revoked"
        await record_audit_event(
            actor=actor,
            action="invite.revoked",
            entity_type="invite",
            entity_id=invite.id,
            metadata={
                "email": invite.email,
                "previous_status": "pending",
                "status": "revoked",
                "role": invite.role,
                "team_id": str(invite.team_id) if invite.team_id else None,
                "team_role": invite.team_role,
                "project_id": str(invite.project_id) if invite.project_id else None,
                "project_role": invite.project_role,
            },
            db=db,
        )


async def accept_invite(
    payload: AcceptInviteRequest, db: AsyncSession
) -> tuple[TokenResponse, str]:
    token_hash = hash_token(payload.token)
    async with transaction(db):
        invite = await db.scalar(select(Invite).where(Invite.token_hash == token_hash))
        if invite is None or invite.status != "pending" or _is_past(invite.expires_at):
            raise InvalidCredentialsError
        user = await db.scalar(select(User).where(User.email == invite.email))
        if user is None:
            user = User(
                email=invite.email,
                name=payload.name,
                password_hash=hash_password(payload.password),
            )
            db.add(user)
            await db.flush()
            db.add(
                IdentityAccount(
                    user_id=user.id,
                    provider="local",
                    provider_subject=user.email,
                    email=user.email,
                )
            )
        else:
            user.name = payload.name or user.name
            user.password_hash = user.password_hash or hash_password(payload.password)
        existing_membership = await db.scalar(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
        )
        if existing_membership is None:
            db.add(
                OrganizationMembership(
                    org_id=invite.org_id,
                    user_id=user.id,
                    role=invite.role,
                    status="active",
                )
            )
        elif existing_membership.org_id != invite.org_id:
            # An account belongs to exactly one organization; the invited email is
            # already a member of a different org.
            raise MemberOrganizationConflictError
        elif existing_membership.status != "active":
            raise InviteLifecycleError
        if invite.team_id and invite.team_role:
            team_membership = await db.scalar(
                select(TeamMembership).where(
                    TeamMembership.team_id == invite.team_id,
                    TeamMembership.user_id == user.id,
                )
            )
            if team_membership is None:
                db.add(
                    TeamMembership(
                        org_id=invite.org_id,
                        team_id=invite.team_id,
                        user_id=user.id,
                        role=invite.team_role,
                    )
                )
        if invite.project_id and invite.project_role:
            project_membership = await db.scalar(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == invite.project_id,
                    ProjectMembership.user_id == user.id,
                )
            )
            if project_membership is None:
                db.add(
                    ProjectMembership(
                        org_id=invite.org_id,
                        project_id=invite.project_id,
                        user_id=user.id,
                        role=invite.project_role,
                    )
                )
        invite.status = "accepted"
        invite.accepted_by_user_id = user.id
        invite.accepted_at = datetime.now(UTC)
        await db.flush()
        principal = await _principal_for_user(user.id, db)
        await record_audit_event(
            actor=principal,
            action="invite.accepted",
            entity_type="invite",
            entity_id=invite.id,
            metadata={
                "email": invite.email,
                "previous_status": "pending",
                "status": "accepted",
                "role": invite.role,
                "team_id": str(invite.team_id) if invite.team_id else None,
                "team_role": invite.team_role,
                "project_id": str(invite.project_id) if invite.project_id else None,
                "project_role": invite.project_role,
            },
            db=db,
        )
        raw_refresh_token = await create_refresh_session(
            user_id=principal.id,
            org_id=principal.org_id,
            db=db,
        )
    return _access_response(principal), raw_refresh_token


async def _require_team(*, team_id: UUID, scope: Scope, db: AsyncSession) -> Team:
    team = await db.scalar(select(Team).where(Team.id == team_id, Team.org_id == scope.org_id))
    if team is None:
        raise InvalidAccessTokenError
    return team


async def _require_project(*, project_id: UUID, scope: Scope, db: AsyncSession) -> Project:
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.org_id == scope.org_id)
    )
    if project is None:
        raise InvalidAccessTokenError
    return project


def _ensure_actor_can_manage_team_members(
    *,
    actor: AuthenticatedUser,
    team_id: UUID,
) -> None:
    if has_permission(actor, "teams.manage"):
        return
    if any(
        item.team_id == team_id and item.role == "team_admin" for item in actor.team_memberships
    ):
        return
    raise PermissionDeniedError


def _ensure_actor_can_manage_project_members(
    *,
    actor: AuthenticatedUser,
    project: Project,
) -> None:
    if has_permission(actor, "projects.manage"):
        return
    if any(
        item.team_id == project.team_id and item.role == "team_admin"
        for item in actor.team_memberships
    ):
        return
    if any(
        item.project_id == project.id and item.role == "project_admin"
        for item in actor.project_memberships
    ):
        return
    raise PermissionDeniedError


async def record_audit_event(
    *,
    actor: AuthenticatedUser,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict,
    db: AsyncSession,
) -> None:
    created_at = datetime.now(UTC)
    metadata = sanitize_metadata(metadata)
    ledger_state = await _audit_ledger_state(org_id=actor.org_id, db=db)
    previous_hash = ledger_state.latest_event_hash
    signing_key, signing_key_id = _current_audit_signing_key()
    event_hash = _audit_event_hash(
        org_id=actor.org_id,
        actor_user_id=actor.id,
        actor_email=str(actor.email),
        actor_role=actor.role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
        previous_hash=previous_hash,
        created_at=created_at,
        secret=signing_key,
    )
    db.add(
        AuditEvent(
            org_id=actor.org_id,
            actor_user_id=actor.id,
            actor_email=str(actor.email),
            actor_role=actor.role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_=metadata,
            previous_hash=previous_hash,
            event_hash=event_hash,
            signature_algorithm="hmac-sha256",
            signing_key_id=signing_key_id,
            created_at=created_at,
        )
    )
    ledger_state.latest_event_hash = event_hash


async def list_audit_events(
    *,
    scope: Scope,
    db: AsyncSession,
    limit: int | None = 100,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    search: str | None = None,
    before_at: datetime | None = None,
    before_id: UUID | None = None,
) -> list[AuditEventResponse]:
    filters = [AuditEvent.org_id == scope.org_id]
    if start_at is not None:
        filters.append(AuditEvent.created_at >= start_at)
    if end_at is not None:
        filters.append(AuditEvent.created_at <= end_at)
    if actor_user_id is not None:
        filters.append(AuditEvent.actor_user_id == actor_user_id)
    if action:
        filters.append(AuditEvent.action == action)
    if entity_type:
        filters.append(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        filters.append(AuditEvent.entity_id == entity_id)
    if search:
        # icontains(autoescape=True) escapes %/_ in the user term so a literal
        # wildcard is matched verbatim rather than altering the search.
        filters.append(
            or_(
                AuditEvent.actor_email.icontains(search, autoescape=True),
                AuditEvent.actor_role.icontains(search, autoescape=True),
                AuditEvent.action.icontains(search, autoescape=True),
                AuditEvent.entity_type.icontains(search, autoescape=True),
                AuditEvent.metadata_["email"].as_string().icontains(search, autoescape=True),
                AuditEvent.metadata_["reason"].as_string().icontains(search, autoescape=True),
                AuditEvent.metadata_["role"].as_string().icontains(search, autoescape=True),
                AuditEvent.metadata_["status"].as_string().icontains(search, autoescape=True),
            )
        )
    if before_at is not None:
        cursor_filter = AuditEvent.created_at < before_at
        if before_id is not None:
            cursor_filter = or_(
                cursor_filter,
                and_(AuditEvent.created_at == before_at, AuditEvent.id < before_id),
            )
        filters.append(cursor_filter)
    query = (
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    events = await db.scalars(query)
    return [
        AuditEventResponse.model_validate({**event.__dict__, "metadata": event.metadata_})
        for event in events
    ]


async def verify_audit_chain(*, scope: Scope, db: AsyncSession):
    from app.modules.auth.schemas import AuditVerificationResponse

    events = list(
        await db.scalars(
            select(AuditEvent)
            .where(AuditEvent.org_id == scope.org_id, AuditEvent.event_hash.is_not(None))
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
    )
    # The ledger anchor records the authoritative chain tip. Comparing the
    # reconstructed tip against it is the only way to detect tail truncation
    # (deletion of the most-recent events leaves a self-consistent prefix).
    ledger_tip = await db.scalar(
        select(AuditLedgerState.latest_event_hash).where(AuditLedgerState.org_id == scope.org_id)
    )
    if not events:
        if ledger_tip is not None:
            return AuditVerificationResponse(
                valid=False,
                checked_events=0,
                reason="ledger tip mismatch (events truncated)",
            )
        return AuditVerificationResponse(valid=True, checked_events=0)
    events_by_previous_hash = {event.previous_hash: event for event in events}
    if len(events_by_previous_hash) != len(events):
        return AuditVerificationResponse(
            valid=False,
            checked_events=0,
            reason="duplicate previous hash",
        )
    keyring = _audit_keyring()
    previous_hash = None
    checked_events = 0
    while previous_hash in events_by_previous_hash:
        event = events_by_previous_hash[previous_hash]
        checked_events += 1
        if event.previous_hash != previous_hash:
            return AuditVerificationResponse(
                valid=False,
                checked_events=checked_events,
                first_invalid_event_id=event.id,
                reason="previous hash mismatch",
            )
        secret = keyring.get(event.signing_key_id)
        if secret is None:
            return AuditVerificationResponse(
                valid=False,
                checked_events=checked_events,
                first_invalid_event_id=event.id,
                reason="unknown signing key",
            )
        expected_hash = _audit_event_hash(
            org_id=event.org_id,
            actor_user_id=event.actor_user_id,
            actor_email=event.actor_email,
            actor_role=event.actor_role,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            metadata=event.metadata_,
            previous_hash=event.previous_hash,
            created_at=event.created_at,
            secret=secret,
        )
        if event.event_hash != expected_hash:
            return AuditVerificationResponse(
                valid=False,
                checked_events=checked_events,
                first_invalid_event_id=event.id,
                reason="event hash mismatch",
            )
        previous_hash = event.event_hash
    if checked_events != len(events):
        return AuditVerificationResponse(
            valid=False,
            checked_events=checked_events,
            reason="chain has unreachable events",
        )
    # `previous_hash` now holds the reconstructed chain tip (the last event's hash).
    if ledger_tip is not None and ledger_tip != previous_hash:
        return AuditVerificationResponse(
            valid=False,
            checked_events=checked_events,
            reason="ledger tip mismatch (events truncated)",
        )
    return AuditVerificationResponse(valid=True, checked_events=checked_events)


async def _latest_audit_hash(*, org_id: UUID, db: AsyncSession) -> str | None:
    return await db.scalar(
        select(AuditEvent.event_hash)
        .where(AuditEvent.org_id == org_id, AuditEvent.event_hash.is_not(None))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )


async def _audit_ledger_state(*, org_id: UUID, db: AsyncSession) -> AuditLedgerState:
    await db.execute(
        update(Organization).where(Organization.id == org_id).values(name=Organization.name)
    )
    await db.execute(
        update(AuditLedgerState)
        .where(AuditLedgerState.org_id == org_id)
        .values(latest_event_hash=AuditLedgerState.latest_event_hash)
    )
    await db.scalar(select(Organization).where(Organization.id == org_id).with_for_update())
    state = await db.scalar(
        select(AuditLedgerState).where(AuditLedgerState.org_id == org_id).with_for_update()
    )
    if state is not None:
        return state
    state = AuditLedgerState(
        org_id=org_id,
        latest_event_hash=await _latest_audit_hash(org_id=org_id, db=db),
    )
    db.add(state)
    await db.flush()
    return state


def _audit_event_hash(
    *,
    org_id: UUID,
    actor_user_id: UUID | None,
    actor_email: str | None,
    actor_role: str | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict,
    previous_hash: str | None,
    created_at: datetime,
    secret: str,
) -> str:
    payload = {
        "org_id": str(org_id),
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "actor_email": actor_email,
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "metadata": metadata,
        "previous_hash": previous_hash,
        "created_at": _audit_timestamp(created_at),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def _audit_key_fingerprint(key: str) -> str:
    return hashlib.sha256(f"bab-audit-kid:{key}".encode()).hexdigest()[:16]


def _current_audit_signing_key() -> tuple[str, str]:
    key = settings.audit_signing_key or settings.secret_key
    return key, _audit_key_fingerprint(key)


def _audit_keyring() -> dict[str | None, str]:
    # Maps signing_key_id -> key. NULL id resolves to the legacy secret_key so that
    # events written before key separation still verify after a JWT-secret rotation.
    ring: dict[str | None, str] = {None: settings.secret_key}
    for key in (settings.secret_key, settings.audit_signing_key):
        if key:
            ring[_audit_key_fingerprint(key)] = key
    return ring


def _audit_timestamp(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat()


def has_permission(user: AuthenticatedUser, permission: str) -> bool:
    return "*" in user.permissions or permission in user.permissions


def _is_past(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value < datetime.now(UTC)


async def _principal_for_user(
    user_id: UUID, db: AsyncSession, *, org_id: UUID | None = None
) -> AuthenticatedUser:
    filters = [
        User.id == user_id,
        User.is_active.is_(True),
        OrganizationMembership.status == "active",
    ]
    # A user belongs to exactly one organization (enforced by a UNIQUE(user_id)
    # constraint on organization_memberships). When the caller knows the target org
    # (e.g. from a token claim) we pin to it; the ordering is defensive only.
    if org_id is not None:
        filters.append(OrganizationMembership.org_id == org_id)
    row = (
        await db.execute(
            select(User, OrganizationMembership)
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .where(*filters)
            .order_by(OrganizationMembership.created_at.asc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise InvalidAccessTokenError
    user, membership = row
    team_memberships = await db.scalars(
        select(TeamMembership).where(
            TeamMembership.org_id == membership.org_id,
            TeamMembership.user_id == user.id,
        )
    )
    project_memberships = await db.scalars(
        select(ProjectMembership).where(
            ProjectMembership.org_id == membership.org_id,
            ProjectMembership.user_id == user.id,
        )
    )
    team_membership_rows = list(team_memberships)
    project_membership_rows = list(project_memberships)
    permissions = sorted(ROLE_PERMISSIONS.get(membership.role, set()))
    return AuthenticatedUser(
        id=user.id,
        org_id=membership.org_id,
        team_id=None,
        email=user.email,
        role=membership.role,
        permissions=permissions,
        team_memberships=[
            AuthenticatedTeamMembership(team_id=item.team_id, role=item.role)
            for item in team_membership_rows
        ],
        project_memberships=[
            AuthenticatedProjectMembership(project_id=item.project_id, role=item.role)
            for item in project_membership_rows
        ],
    )


def _access_response(principal: AuthenticatedUser) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(
            user_id=principal.id,
            org_id=principal.org_id,
            role=principal.role,
        ),
    )


def _invite_response(
    invite: Invite,
    *,
    raw_token: str | None,
    public_base_url: str | None,
) -> InviteResponse:
    invite_url = None
    if raw_token:
        base_url = (public_base_url or "").rstrip("/")
        invite_url = (
            f"{base_url}/accept-invite?token={raw_token}"
            if base_url
            else f"/accept-invite?token={raw_token}"
        )
    status = (
        "expired" if invite.status == "pending" and _is_past(invite.expires_at) else invite.status
    )
    return InviteResponse(
        id=invite.id,
        org_id=invite.org_id,
        team_id=invite.team_id,
        project_id=invite.project_id,
        email=invite.email,
        role=invite.role,
        team_role=invite.team_role,
        project_role=invite.project_role,
        status=status,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        created_at=invite.created_at,
        invite_url=invite_url,
    )
