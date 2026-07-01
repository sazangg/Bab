from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_permission
from app.api.v1.rate_limits import (
    enforce_auth_login_rate_limit,
    enforce_invite_accept_rate_limit,
    enforce_refresh_rate_limit,
)
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
    MemberAlreadyExistsError,
    MemberNotFoundError,
    MemberOrganizationConflictError,
    PermissionDeniedError,
)
from app.modules.auth.schemas import (
    AcceptInviteRequest,
    AuthenticatedUser,
    CreateInviteRequest,
    CreateMemberRequest,
    InvitePreviewResponse,
    InviteResponse,
    LoginRequest,
    MemberResponse,
    TokenResponse,
    UpdateMemberRequest,
    UpdateMemberStatusRequest,
)
from app.modules.authorization.permissions import Permissions
from app.modules.settings import facade as settings_facade

REFRESH_COOKIE_NAME = "bab_refresh_token"

router = APIRouter(prefix="/auth", tags=["auth"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]
RequestScope = Annotated[Scope, Depends(get_scope)]
MemberAdmin = Annotated[AuthenticatedUser, Depends(require_permission(Permissions.MEMBERS_MANAGE))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> TokenResponse:
    await enforce_auth_login_rate_limit(request=request, email=payload.email)
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
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> TokenResponse:
    await enforce_invite_accept_rate_limit(request=request, token=payload.token)
    try:
        token_response, raw_refresh_token = await facade.accept_invite(payload, db)
    except MemberOrganizationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this account already belongs to another organization",
        ) from exc
    except (InvalidCredentialsError, InviteLifecycleError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid invite"
        ) from exc
    _set_refresh_cookie(response, raw_refresh_token)
    return token_response


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: DatabaseSession,
    raw_refresh_token: RefreshCookie = None,
) -> TokenResponse:
    await enforce_refresh_rate_limit(request=request, refresh_token=raw_refresh_token)
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


@router.get("/invites/preview")
async def preview_invite(token: str, db: DatabaseSession) -> InvitePreviewResponse:
    try:
        return await facade.preview_invite(token=token, db=db)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="invite not found") from exc


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
    except InvalidInviteTargetError as exc:
        raise HTTPException(status_code=400, detail="invalid member target") from exc
    except MemberAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="member already exists") from exc
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
    request: Request,
    scope: RequestScope,
    db: DatabaseSession,
    actor: CurrentUser,
) -> InviteResponse:
    try:
        org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
        return await facade.create_invite(
            payload=payload,
            actor=actor,
            scope=scope,
            public_base_url=org_settings.public_app_url or _request_origin(request),
            db=db,
        )
    except InvalidInviteTargetError as exc:
        raise HTTPException(status_code=400, detail="invalid invite target") from exc
    except MemberAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="member already exists") from exc
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


def _request_origin(request: Request) -> str | None:
    for value in (request.headers.get("origin"), request.headers.get("referer")):
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


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
