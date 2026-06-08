import csv
import json
from datetime import datetime
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import Response as FastApiResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_permission
from app.core.config import settings
from app.core.database import Scope, get_db
from app.modules.auth import facade
from app.modules.auth.errors import (
    DuplicateInviteError,
    InvalidCredentialsError,
    InvalidInviteTargetError,
    InvalidRefreshTokenError,
    InviteLifecycleError,
    InviteNotFoundError,
    LastOwnerError,
    MemberNotFoundError,
    PermissionDeniedError,
)
from app.modules.auth.schemas import (
    AcceptInviteRequest,
    AuditEventResponse,
    AuditVerificationResponse,
    AuthenticatedUser,
    CreateInviteRequest,
    CreateMemberRequest,
    InviteResponse,
    LoginRequest,
    MemberResponse,
    TokenResponse,
    UpdateMemberRequest,
    UpdateMemberStatusRequest,
)

REFRESH_COOKIE_NAME = "bab_refresh_token"

router = APIRouter(prefix="/auth", tags=["auth"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]
RequestScope = Annotated[Scope, Depends(get_scope)]
MemberAdmin = Annotated[AuthenticatedUser, Depends(require_permission("members.manage"))]
AuditViewer = Annotated[AuthenticatedUser, Depends(require_permission("audit.view"))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    db: DatabaseSession,
) -> TokenResponse:
    try:
        token_response, raw_refresh_token = await facade.login(payload, db)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        ) from exc

    _set_refresh_cookie(response, raw_refresh_token)
    return token_response


@router.post("/invites/accept")
async def accept_invite(
    payload: AcceptInviteRequest,
    response: Response,
    db: DatabaseSession,
) -> TokenResponse:
    try:
        token_response, raw_refresh_token = await facade.accept_invite(payload, db)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid invite"
        ) from exc
    _set_refresh_cookie(response, raw_refresh_token)
    return token_response


@router.post("/refresh")
async def refresh(
    response: Response,
    db: DatabaseSession,
    raw_refresh_token: RefreshCookie = None,
) -> TokenResponse:
    try:
        token_response, new_raw_refresh_token = await facade.refresh(raw_refresh_token, db)
    except InvalidRefreshTokenError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid refresh token",
        ) from exc

    _set_refresh_cookie(response, new_raw_refresh_token)
    return token_response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: DatabaseSession,
    raw_refresh_token: RefreshCookie = None,
) -> None:
    await facade.logout(raw_refresh_token, db)
    _clear_refresh_cookie(response)


@router.get("/me")
async def me(user: CurrentUser) -> AuthenticatedUser:
    return user


@router.get("/members")
async def list_members(
    scope: RequestScope,
    db: DatabaseSession,
    _: MemberAdmin,
) -> list[MemberResponse]:
    return await facade.list_members(scope=scope, db=db)


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: CreateMemberRequest,
    scope: RequestScope,
    db: DatabaseSession,
    actor: MemberAdmin,
) -> MemberResponse:
    try:
        return await facade.create_member(payload=payload, actor=actor, scope=scope, db=db)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.patch("/members/{user_id}")
async def update_member(
    user_id: UUID,
    payload: UpdateMemberRequest,
    scope: RequestScope,
    db: DatabaseSession,
    actor: MemberAdmin,
) -> MemberResponse:
    try:
        return await facade.update_member(
            user_id=user_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except LastOwnerError as exc:
        raise HTTPException(status_code=400, detail="cannot demote the last owner") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="member not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.patch("/members/{user_id}/status")
async def update_member_status(
    user_id: UUID,
    payload: UpdateMemberStatusRequest,
    scope: RequestScope,
    db: DatabaseSession,
    actor: MemberAdmin,
) -> MemberResponse:
    try:
        return await facade.update_member_status(
            user_id=user_id,
            payload=payload,
            actor=actor,
            scope=scope,
            db=db,
        )
    except LastOwnerError as exc:
        raise HTTPException(status_code=400, detail="cannot deactivate the last owner") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="member not found") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.get("/invites")
async def list_invites(
    scope: RequestScope,
    db: DatabaseSession,
    actor: CurrentUser,
) -> list[InviteResponse]:
    return await facade.list_invites(actor=actor, scope=scope, db=db)


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: CreateInviteRequest,
    scope: RequestScope,
    db: DatabaseSession,
    actor: CurrentUser,
) -> InviteResponse:
    try:
        return await facade.create_invite(
            payload=payload,
            actor=actor,
            scope=scope,
            public_base_url=None,
            db=db,
        )
    except InvalidInviteTargetError as exc:
        raise HTTPException(status_code=400, detail="invalid invite target") from exc
    except DuplicateInviteError as exc:
        raise HTTPException(status_code=409, detail="pending invite already exists") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: UUID,
    scope: RequestScope,
    db: DatabaseSession,
    actor: CurrentUser,
) -> None:
    try:
        await facade.revoke_invite(invite_id=invite_id, actor=actor, scope=scope, db=db)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="invite not found") from exc
    except InviteLifecycleError as exc:
        raise HTTPException(status_code=400, detail="invite is not pending") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="insufficient permissions") from exc


@router.get("/audit")
async def list_audit_events(
    scope: RequestScope,
    db: DatabaseSession,
    _: AuditViewer,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    limit: int = 100,
) -> list[AuditEventResponse]:
    return await facade.list_audit_events(
        scope=scope,
        db=db,
        limit=min(max(limit, 1), 500),
        start_at=start_at,
        end_at=end_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    )


@router.get("/audit/export")
async def export_audit_events(
    scope: RequestScope,
    db: DatabaseSession,
    _: AuditViewer,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
) -> FastApiResponse:
    events = await facade.list_audit_events(
        scope=scope,
        db=db,
        limit=None,
        start_at=start_at,
        end_at=end_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return _csv_response(
        filename="bab-audit-events.csv",
        header=[
            "id",
            "created_at",
            "org_id",
            "actor_user_id",
            "actor_email",
            "actor_role",
            "action",
            "entity_type",
            "entity_id",
            "metadata",
            "previous_hash",
            "event_hash",
            "signature_algorithm",
        ],
        rows=[
            [
                event.id,
                event.created_at,
                event.org_id,
                event.actor_user_id,
                event.actor_email,
                event.actor_role,
                event.action,
                event.entity_type,
                event.entity_id,
                json.dumps(event.metadata, sort_keys=True),
                event.previous_hash,
                event.event_hash,
                event.signature_algorithm,
            ]
            for event in events
        ],
    )


@router.get("/audit/verify")
async def verify_audit_chain(
    scope: RequestScope,
    db: DatabaseSession,
    _: AuditViewer,
) -> AuditVerificationResponse:
    return await facade.verify_audit_chain(scope=scope, db=db)


def _csv_response(*, filename: str, header: list[str], rows: list[list[object]]) -> FastApiResponse:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return FastApiResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _set_refresh_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=value,
        httponly=True,
        secure=_refresh_cookie_secure(),
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain,
        path=settings.refresh_cookie_path,
        max_age=60 * 60 * 24 * 30,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        domain=settings.refresh_cookie_domain,
        path=settings.refresh_cookie_path,
        secure=_refresh_cookie_secure(),
        samesite=settings.refresh_cookie_samesite,
    )


def _refresh_cookie_secure() -> bool:
    if settings.refresh_cookie_secure is not None:
        return settings.refresh_cookie_secure
    return settings.environment == "production"
