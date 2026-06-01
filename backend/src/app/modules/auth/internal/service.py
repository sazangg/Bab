import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
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
from app.modules.auth.errors import (
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    LastOwnerError,
)
from app.modules.auth.internal.models import (
    AuditEvent,
    IdentityAccount,
    Invite,
    OrganizationMembership,
    Team,
    TeamMembership,
    User,
)
from app.modules.auth.schemas import (
    AcceptInviteRequest,
    AuditEventResponse,
    AuthenticatedTeamMembership,
    AuthenticatedUser,
    CreateInviteRequest,
    CreateMemberRequest,
    InviteResponse,
    LoginRequest,
    MemberResponse,
    TeamMemberResponse,
    TokenResponse,
    UpdateMemberRequest,
    UpdateMemberStatusRequest,
    UpdateTeamMemberRequest,
    UpsertTeamMemberRequest,
)

MOCK_ADMIN_ID = UUID("00000000-0000-4000-8000-000000000001")
REFRESH_TOKEN_TTL = timedelta(days=30)
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
        "audit.view",
    },
    "org_member": set(),
}


async def login(payload: LoginRequest, db: AsyncSession) -> tuple[TokenResponse, str]:
    user = await db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user is None or not user.is_active or not user.password_hash:
        raise InvalidCredentialsError
    try:
        password_is_valid = verify_password(payload.password, user.password_hash)
    except SecurityError as exc:
        raise InvalidCredentialsError from exc
    if not password_is_valid:
        raise InvalidCredentialsError

    principal = await _principal_for_user(user.id, db)
    raw_refresh_token = _create_refresh_token(principal)
    return _access_response(principal), raw_refresh_token


async def refresh(raw_refresh_token: str | None, db: AsyncSession) -> tuple[TokenResponse, str]:
    if not raw_refresh_token:
        raise InvalidRefreshTokenError

    try:
        claims = decode_access_token(raw_refresh_token, expected_type="refresh")
        user_id = UUID(str(claims.get("sub")))
    except (SecurityError, ValueError, TypeError) as exc:
        raise InvalidRefreshTokenError from exc

    principal = await _principal_for_user(user_id, db)
    return _access_response(principal), _create_refresh_token(principal)


async def logout(raw_refresh_token: str | None, db: AsyncSession) -> None:
    if not raw_refresh_token:
        return


async def verify_access_token(token: str, db: AsyncSession) -> AuthenticatedUser:
    try:
        claims = decode_access_token(token)
        user_id = UUID(str(claims.get("sub")))
    except (SecurityError, ValueError, TypeError) as exc:
        raise InvalidAccessTokenError from exc

    return await _principal_for_user(user_id, db)


async def list_members(*, scope: Scope, db: AsyncSession) -> list[MemberResponse]:
    rows = await db.execute(
        select(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(OrganizationMembership.org_id == scope.org_id)
        .order_by(User.email)
    )
    return [
        MemberResponse(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=membership.role,
            status=membership.status,
            created_at=membership.created_at,
        )
        for user, membership in rows
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
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
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
        else:
            user.name = payload.name or user.name
            user.password_hash = hash_password(payload.password)
            user.is_active = True
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == scope.org_id,
                OrganizationMembership.user_id == user.id,
            )
        )
        if membership is None:
            membership = OrganizationMembership(
                org_id=scope.org_id,
                user_id=user.id,
                role=payload.role,
                status="active",
            )
            db.add(membership)
        else:
            membership.role = payload.role
            membership.status = "active"
        await db.flush()
        await record_audit_event(
            actor=actor,
            action="member.created",
            entity_type="user",
            entity_id=user.id,
            metadata={"email": email, "role": payload.role},
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
            raise InvalidAccessTokenError
        if membership.role == "org_owner" and payload.role != "org_owner":
            await _ensure_not_last_owner(scope=scope, excluding_user_id=user_id, db=db)
        membership.role = payload.role
        await db.flush()
        await record_audit_event(
            actor=actor,
            action="member.role_updated",
            entity_type="user",
            entity_id=user_id,
            metadata={"role": payload.role},
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
            raise InvalidAccessTokenError
        user, membership = row
        if payload.status == "inactive":
            if membership.role == "org_owner":
                await _ensure_not_last_owner(scope=scope, excluding_user_id=user_id, db=db)
            membership.status = "inactive"
            user.is_active = False
        else:
            membership.status = "active"
            user.is_active = True
        await db.flush()
        await record_audit_event(
            actor=actor,
            action="member.status_updated",
            entity_type="user",
            entity_id=user_id,
            metadata={"status": payload.status},
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
        team_membership = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.org_id == scope.org_id,
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id,
            )
        )
        if team_membership is None:
            return
        await db.delete(team_membership)
        await record_audit_event(
            actor=actor,
            action="team_member.removed",
            entity_type="team_member",
            entity_id=team_membership.id,
            metadata={"team_id": str(team_id), "user_id": str(user_id)},
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
        invite = Invite(
            org_id=scope.org_id,
            team_id=payload.team_id,
            email=str(payload.email).lower(),
            role=payload.role,
            team_role=payload.team_role,
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
            metadata={"email": invite.email, "role": invite.role},
            db=db,
        )
    return _invite_response(invite, raw_token=raw_token, public_base_url=public_base_url)


async def list_invites(*, scope: Scope, db: AsyncSession) -> list[InviteResponse]:
    invites = await db.scalars(
        select(Invite).where(Invite.org_id == scope.org_id).order_by(Invite.created_at.desc())
    )
    return [_invite_response(invite, raw_token=None, public_base_url=None) for invite in invites]


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
            return
        invite.status = "revoked"
        await record_audit_event(
            actor=actor,
            action="invite.revoked",
            entity_type="invite",
            entity_id=invite.id,
            metadata={"email": invite.email},
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
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.org_id == invite.org_id,
                OrganizationMembership.user_id == user.id,
            )
        )
        if membership is None:
            db.add(
                OrganizationMembership(
                    org_id=invite.org_id,
                    user_id=user.id,
                    role=invite.role,
                    status="active",
                )
            )
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
        invite.status = "accepted"
        invite.accepted_by_user_id = user.id
        invite.accepted_at = datetime.now(UTC)
        await db.flush()
        principal = await _principal_for_user(user.id, db)
    return _access_response(principal), _create_refresh_token(principal)


async def _require_team(*, team_id: UUID, scope: Scope, db: AsyncSession) -> Team:
    team = await db.scalar(select(Team).where(Team.id == team_id, Team.org_id == scope.org_id))
    if team is None:
        raise InvalidAccessTokenError
    return team


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
    previous_hash = await _latest_audit_hash(org_id=actor.org_id, db=db)
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
            created_at=created_at,
        )
    )


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
    query = select(AuditEvent).where(*filters).order_by(AuditEvent.created_at.desc())
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
    if not events:
        return AuditVerificationResponse(valid=True, checked_events=0)
    events_by_previous_hash = {event.previous_hash: event for event in events}
    if len(events_by_previous_hash) != len(events):
        return AuditVerificationResponse(
            valid=False,
            checked_events=0,
            reason="duplicate previous hash",
        )
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
    return AuditVerificationResponse(valid=True, checked_events=checked_events)


async def _latest_audit_hash(*, org_id: UUID, db: AsyncSession) -> str | None:
    return await db.scalar(
        select(AuditEvent.event_hash)
        .where(AuditEvent.org_id == org_id, AuditEvent.event_hash.is_not(None))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )


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
        settings.secret_key.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


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


async def _principal_for_user(user_id: UUID, db: AsyncSession) -> AuthenticatedUser:
    row = (
        await db.execute(
            select(User, OrganizationMembership)
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                OrganizationMembership.status == "active",
            )
            .order_by(OrganizationMembership.created_at.asc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise InvalidAccessTokenError
    user, membership = row
    permissions = sorted(ROLE_PERMISSIONS.get(membership.role, set()))
    team_memberships = await db.scalars(
        select(TeamMembership).where(
            TeamMembership.org_id == membership.org_id,
            TeamMembership.user_id == user.id,
        )
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
            for item in team_memberships
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


def _create_refresh_token(principal: AuthenticatedUser) -> str:
    return create_access_token(
        user_id=principal.id,
        org_id=principal.org_id,
        role=principal.role,
        expires_delta=REFRESH_TOKEN_TTL,
        token_type="refresh",
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
    return InviteResponse(
        id=invite.id,
        org_id=invite.org_id,
        team_id=invite.team_id,
        email=invite.email,
        role=invite.role,
        team_role=invite.team_role,
        status=invite.status,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        created_at=invite.created_at,
        invite_url=invite_url,
    )
