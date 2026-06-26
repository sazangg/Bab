from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.modules.audit import facade as audit_facade
from app.modules.auth import read_models
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
    IdentityAccount,
    Invite,
    Organization,
    OrganizationMembership,
    ProjectMembership,
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
    OrganizationIdentity,
    ProjectMemberResponse,
    TeamMemberResponse,
    TokenResponse,
    UpdateMemberRequest,
    UpdateMemberStatusRequest,
    UpdateProjectMemberRequest,
    UpdateTeamMemberRequest,
    UpsertProjectMemberRequest,
    UpsertTeamMemberRequest,
    UserLabel,
)
from app.modules.authorization import facade as authorization_facade
from app.modules.authorization.permissions import Permissions
from app.modules.authorization.schemas import (
    AuthorizationDecision,
    MemberInviteTarget,
    MemberRoleChangeTarget,
    MemberStatusChangeTarget,
    ScopedMembershipTarget,
)
from app.modules.workspace import facade as workspace_facade
from app.modules.workspace.internal.models import Team
from app.modules.workspace.schemas import ProjectMembershipTarget

MOCK_ADMIN_ID = UUID("00000000-0000-4000-8000-000000000001")
INVITE_TOKEN_TTL = timedelta(days=7)

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
        await audit_facade.record_audit_event(
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


async def has_team_membership(
    *, org_id: UUID, team_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    membership = await db.scalar(
        select(TeamMembership).where(
            TeamMembership.org_id == org_id,
            TeamMembership.team_id == team_id,
            TeamMembership.user_id == user_id,
        )
    )
    return membership is not None


async def has_team_admin_membership(
    *, org_id: UUID, team_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    membership = await db.scalar(
        select(TeamMembership).where(
            TeamMembership.org_id == org_id,
            TeamMembership.team_id == team_id,
            TeamMembership.user_id == user_id,
            TeamMembership.role == "team_admin",
        )
    )
    return membership is not None


async def has_project_membership(
    *, org_id: UUID, project_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    membership = await db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.org_id == org_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
    )
    return membership is not None


async def has_project_admin_membership(
    *, org_id: UUID, project_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    membership = await db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.org_id == org_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
            ProjectMembership.role == "project_admin",
        )
    )
    return membership is not None


async def get_organization_identity(
    *, org_id: UUID, db: AsyncSession
) -> OrganizationIdentity | None:
    organization = await db.get(Organization, org_id)
    if organization is None:
        return None
    return OrganizationIdentity(id=organization.id, name=organization.name)


async def update_organization_name(
    *, org_id: UUID, name: str, db: AsyncSession
) -> None:
    organization = await db.get(Organization, org_id)
    if organization is not None:
        organization.name = name


async def get_user_labels(
    *, org_id: UUID, user_ids: set[UUID], db: AsyncSession
) -> dict[UUID, UserLabel]:
    return await read_models.get_user_labels(org_id=org_id, user_ids=user_ids, db=db)


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
                effective_permissions=authorization_facade.effective_permissions_for_member(
                    org_role=membership.role,
                    team_roles=[item.role for item in team_memberships],
                    project_roles=[item.role for item in project_memberships],
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
        _raise_permission_denied(
            authorization_facade.can_manage_org_role(
                actor=actor,
                target=MemberRoleChangeTarget(current_role=None, new_role=payload.role),
            )
        )
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
            _raise_permission_denied(
                authorization_facade.can_manage_org_role(
                    actor=actor,
                    target=MemberRoleChangeTarget(
                        current_role=membership.role,
                        new_role=payload.role,
                    ),
                )
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
        await audit_facade.record_audit_event(
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
        _raise_permission_denied(
            authorization_facade.can_manage_org_role(
                actor=actor,
                target=MemberRoleChangeTarget(
                    current_role=membership.role,
                    new_role=payload.role,
                ),
            )
        )
        previous_role = membership.role
        if previous_role == "org_owner" and payload.role != "org_owner":
            await _ensure_not_last_owner(scope=scope, excluding_user_id=user_id, db=db)
        _raise_permission_denied(
            authorization_facade.can_change_member_role_without_self_demotion(
                actor=actor,
                target=MemberRoleChangeTarget(
                    target_user_id=user_id,
                    current_role=previous_role,
                    new_role=payload.role,
                ),
            )
        )
        membership.role = payload.role
        await db.flush()
        await audit_facade.record_audit_event(
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
        _raise_permission_denied(
            authorization_facade.can_manage_org_role(
                actor=actor,
                target=MemberRoleChangeTarget(
                    current_role=membership.role,
                    new_role=membership.role,
                ),
            )
        )
        # Activation is gated per organization via membership.status, NOT the global
        # User.is_active flag. Toggling the shared user row here would let one org's
        # admin lock the user out of (or re-enable them in) another org.
        del user
        if payload.status == "inactive":
            if membership.role == "org_owner":
                await _ensure_not_last_owner(scope=scope, excluding_user_id=user_id, db=db)
            if actor.id == user_id:
                _raise_permission_denied(
                    authorization_facade.can_change_member_status(
                        actor=actor,
                        target=MemberStatusChangeTarget(
                            target_user_id=user_id,
                            current_role=membership.role,
                            new_status="inactive",
                        ),
                    )
                )
            previous_status = membership.status
            membership.status = "inactive"
        else:
            previous_status = membership.status
            membership.status = "active"
        await db.flush()
        await audit_facade.record_audit_event(
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


def _raise_permission_denied(decision: AuthorizationDecision) -> None:
    if not decision.allowed:
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
        _raise_permission_denied(
            authorization_facade.can_manage_scoped_membership(
                actor=actor,
                permission=Permissions.TEAMS_MANAGE,
                target=ScopedMembershipTarget(scope_type="team", team_id=team_id),
            )
        )
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
        await audit_facade.record_audit_event(
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
        _raise_permission_denied(
            authorization_facade.can_manage_scoped_membership(
                actor=actor,
                permission=Permissions.TEAMS_MANAGE,
                target=ScopedMembershipTarget(scope_type="team", team_id=team_id),
            )
        )
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
        await audit_facade.record_audit_event(
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
        _raise_permission_denied(
            authorization_facade.can_manage_scoped_membership(
                actor=actor,
                permission=Permissions.PROJECTS_MANAGE,
                target=ScopedMembershipTarget(
                    scope_type="project",
                    project_id=project.id,
                    project_team_id=project.team_id,
                ),
            )
        )
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
        await audit_facade.record_audit_event(
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
        _raise_permission_denied(
            authorization_facade.can_manage_scoped_membership(
                actor=actor,
                permission=Permissions.PROJECTS_MANAGE,
                target=ScopedMembershipTarget(
                    scope_type="project",
                    project_id=project.id,
                    project_team_id=project.team_id,
                ),
            )
        )
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
        await audit_facade.record_audit_event(
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
        _raise_permission_denied(
            authorization_facade.can_create_member_invite(
                actor=actor,
                target=MemberInviteTarget(
                    org_role=payload.role,
                    team_id=payload.team_id,
                    team_role=payload.team_role,
                    project_id=project.id if project else None,
                    project_team_id=project.team_id if project else None,
                    project_role=payload.project_role,
                ),
            )
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
        await audit_facade.record_audit_event(
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
        if authorization_facade.can_manage_member_invite(
            actor=actor,
            target=_member_invite_target(
                invite=invite,
                project_team_id=project_team_by_id.get(invite.project_id),
            ),
        ).allowed
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
        await _project_target(project_id=invite.project_id, scope=Scope(invite.org_id), db=db)
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
) -> tuple[Team | None, ProjectMembershipTarget | None]:
    return await _validate_scoped_target(payload=payload, scope=scope, db=db)


async def _validate_scoped_target(
    *,
    payload: CreateInviteRequest | CreateMemberRequest,
    scope: Scope,
    db: AsyncSession,
) -> tuple[Team | None, ProjectMembershipTarget | None]:
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
        project = await _project_target(project_id=payload.project_id, scope=scope, db=db)
        if project is None or not project.is_active:
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


async def _project_team_by_id(*, scope: Scope, db: AsyncSession) -> dict[UUID, UUID]:
    return await workspace_facade.get_project_team_ids(scope=scope, db=db)


async def _project_target(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectMembershipTarget | None:
    return await workspace_facade.get_project_membership_target(
        project_id=project_id,
        scope=scope,
        db=db,
    )


def _member_invite_target(*, invite: Invite, project_team_id: UUID | None) -> MemberInviteTarget:
    return MemberInviteTarget(
        org_role=invite.role,
        team_id=invite.team_id,
        team_role=invite.team_role,
        project_id=invite.project_id,
        project_team_id=project_team_id,
        project_role=invite.project_role,
    )


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
            project = await _project_target(project_id=invite.project_id, scope=scope, db=db)
            project_team_id = project.team_id if project else None
        _raise_permission_denied(
            authorization_facade.can_manage_member_invite(
                actor=actor,
                target=_member_invite_target(invite=invite, project_team_id=project_team_id),
            )
        )
        if invite.status != "pending" or _is_past(invite.expires_at):
            raise InviteLifecycleError
        invite.status = "revoked"
        await audit_facade.record_audit_event(
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
        await audit_facade.record_audit_event(
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


async def _require_project(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> ProjectMembershipTarget:
    project = await _project_target(project_id=project_id, scope=scope, db=db)
    if project is None:
        raise InvalidAccessTokenError
    return project


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
    permissions = authorization_facade.effective_permissions_for_member(
        org_role=membership.role,
        team_roles=[],
        project_roles=[],
    )
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
