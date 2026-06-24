from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth import read_models
from app.modules.auth.internal import service
from app.modules.auth.schemas import (
    AcceptInviteRequest,
    AuditEventResponse,
    AuthenticatedUser,
    CreateInviteRequest,
    CreateMemberRequest,
    InvitePreviewResponse,
    InviteResponse,
    LoginRequest,
    MemberOptionResponse,
    MemberResponse,
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


async def login(payload: LoginRequest, db: AsyncSession) -> tuple[TokenResponse, str]:
    return await service.login(payload, db)


async def refresh(raw_refresh_token: str | None, db: AsyncSession) -> tuple[TokenResponse, str]:
    return await service.refresh(raw_refresh_token, db)


async def logout(raw_refresh_token: str | None, db: AsyncSession) -> None:
    await service.logout(raw_refresh_token, db)


async def verify_access_token(token: str, db: AsyncSession) -> AuthenticatedUser:
    return await service.verify_access_token(token, db)


def has_permission(user: AuthenticatedUser, permission: str) -> bool:
    return service.has_permission(user, permission)


async def has_team_membership(
    *, org_id: UUID, team_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    return await service.has_team_membership(
        org_id=org_id,
        team_id=team_id,
        user_id=user_id,
        db=db,
    )


async def has_team_admin_membership(
    *, org_id: UUID, team_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    return await service.has_team_admin_membership(
        org_id=org_id,
        team_id=team_id,
        user_id=user_id,
        db=db,
    )


async def has_project_membership(
    *, org_id: UUID, project_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    return await service.has_project_membership(
        org_id=org_id,
        project_id=project_id,
        user_id=user_id,
        db=db,
    )


async def has_project_admin_membership(
    *, org_id: UUID, project_id: UUID, user_id: UUID, db: AsyncSession
) -> bool:
    return await service.has_project_admin_membership(
        org_id=org_id,
        project_id=project_id,
        user_id=user_id,
        db=db,
    )


async def get_organization_identity(
    *, org_id: UUID, db: AsyncSession
) -> OrganizationIdentity | None:
    return await service.get_organization_identity(org_id=org_id, db=db)


async def update_organization_name(*, org_id: UUID, name: str, db: AsyncSession) -> None:
    await service.update_organization_name(org_id=org_id, name=name, db=db)


async def get_user_labels(
    *, org_id: UUID, user_ids: set[UUID], db: AsyncSession
) -> dict[UUID, UserLabel]:
    return await read_models.get_user_labels(org_id=org_id, user_ids=user_ids, db=db)


async def list_members(*, scope: Scope, db: AsyncSession) -> list[MemberResponse]:
    return await service.list_members(scope=scope, db=db)


async def list_member_options(*, scope: Scope, db: AsyncSession) -> list[MemberOptionResponse]:
    return await service.list_member_options(scope=scope, db=db)


async def create_member(
    *,
    payload: CreateMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> MemberResponse:
    return await service.create_member(payload=payload, actor=actor, scope=scope, db=db)


async def update_member(
    *,
    user_id: UUID,
    payload: UpdateMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> MemberResponse:
    return await service.update_member(
        user_id=user_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def update_member_status(
    *,
    user_id: UUID,
    payload: UpdateMemberStatusRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> MemberResponse:
    return await service.update_member_status(
        user_id=user_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_team_members(
    *, team_id: UUID, scope: Scope, db: AsyncSession
) -> list[TeamMemberResponse]:
    return await service.list_team_members(team_id=team_id, scope=scope, db=db)


async def upsert_team_member(
    *,
    team_id: UUID,
    payload: UpsertTeamMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamMemberResponse:
    return await service.upsert_team_member(
        team_id=team_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def update_team_member(
    *,
    team_id: UUID,
    user_id: UUID,
    payload: UpdateTeamMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> TeamMemberResponse:
    return await service.update_team_member(
        team_id=team_id,
        user_id=user_id,
        payload=payload,
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
    await service.remove_team_member(
        team_id=team_id,
        user_id=user_id,
        actor=actor,
        scope=scope,
        db=db,
    )


async def list_project_members(
    *, project_id: UUID, scope: Scope, db: AsyncSession
) -> list[ProjectMemberResponse]:
    return await service.list_project_members(project_id=project_id, scope=scope, db=db)


async def upsert_project_member(
    *,
    project_id: UUID,
    payload: UpsertProjectMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectMemberResponse:
    return await service.upsert_project_member(
        project_id=project_id,
        payload=payload,
        actor=actor,
        scope=scope,
        db=db,
    )


async def update_project_member(
    *,
    project_id: UUID,
    user_id: UUID,
    payload: UpdateProjectMemberRequest,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> ProjectMemberResponse:
    return await service.update_project_member(
        project_id=project_id,
        user_id=user_id,
        payload=payload,
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
    await service.remove_project_member(
        project_id=project_id,
        user_id=user_id,
        actor=actor,
        scope=scope,
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
    return await service.create_invite(
        payload=payload,
        actor=actor,
        scope=scope,
        public_base_url=public_base_url,
        db=db,
    )


async def list_invites(
    *,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> list[InviteResponse]:
    return await service.list_invites(actor=actor, scope=scope, db=db)


async def preview_invite(*, token: str, db: AsyncSession) -> InvitePreviewResponse:
    return await service.preview_invite(token=token, db=db)


async def revoke_invite(
    *,
    invite_id: UUID,
    actor: AuthenticatedUser,
    scope: Scope,
    db: AsyncSession,
) -> None:
    await service.revoke_invite(invite_id=invite_id, actor=actor, scope=scope, db=db)


async def accept_invite(
    payload: AcceptInviteRequest, db: AsyncSession
) -> tuple[TokenResponse, str]:
    return await service.accept_invite(payload, db)


async def list_audit_events(
    *,
    scope: Scope,
    db: AsyncSession,
    limit: int | None = 100,
    start_at=None,
    end_at=None,
    actor_user_id=None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id=None,
    search: str | None = None,
    before_at=None,
    before_id=None,
) -> list[AuditEventResponse]:
    return await service.list_audit_events(
        scope=scope,
        db=db,
        limit=limit,
        start_at=start_at,
        end_at=end_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        search=search,
        before_at=before_at,
        before_id=before_id,
    )


async def verify_audit_chain(*, scope: Scope, db: AsyncSession):
    return await service.verify_audit_chain(scope=scope, db=db)


async def record_audit_event(
    *,
    actor: AuthenticatedUser,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict,
    db: AsyncSession,
) -> None:
    await service.record_audit_event(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
        db=db,
    )
