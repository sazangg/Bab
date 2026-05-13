import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transaction
from app.core.security import (
    SecurityError,
    create_access_token,
    decode_access_token,
    hash_token,
    verify_password,
)
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.errors import (
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.modules.auth.internal import repository
from app.modules.auth.internal.models import RefreshToken, User
from app.modules.auth.schemas import AuthenticatedUser, LoginRequest, TokenResponse

REFRESH_TOKEN_TTL = timedelta(days=30)


async def login(payload: LoginRequest, db: AsyncSession) -> tuple[TokenResponse, str]:
    user = await repository.get_user_by_email(payload.email, db)
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        await _record_failed_login(payload.email, user, db)
        raise InvalidCredentialsError

    async with transaction(db):
        raw_refresh_token, _ = await _issue_refresh_token(user, db)
        await audit_facade.record_event(
            RecordAuditEvent(
                org_id=user.org_id,
                actor_user_id=user.id,
                event="auth.login_success",
                target_type="user",
                target_id=user.id,
            ),
            db,
        )

    return _access_response(user), raw_refresh_token


async def refresh(raw_refresh_token: str | None, db: AsyncSession) -> tuple[TokenResponse, str]:
    if not raw_refresh_token:
        raise InvalidRefreshTokenError

    refresh_token = await repository.get_refresh_token_by_hash(hash_token(raw_refresh_token), db)
    if refresh_token is None or _as_utc(refresh_token.expires_at) <= datetime.now(UTC):
        raise InvalidRefreshTokenError

    if refresh_token.revoked_at is not None:
        await _handle_refresh_reuse(refresh_token, db)
        raise InvalidRefreshTokenError

    user = await repository.get_user_by_id(refresh_token.user_id, db)
    if user is None or not user.is_active:
        raise InvalidRefreshTokenError

    async with transaction(db):
        raw_new_refresh_token, new_refresh_token = await _issue_refresh_token(user, db)
        await repository.revoke_refresh_token(
            refresh_token,
            db=db,
            replaced_by_token_id=new_refresh_token.id,
        )

    return _access_response(user), raw_new_refresh_token


async def logout(raw_refresh_token: str | None, db: AsyncSession) -> None:
    if not raw_refresh_token:
        return

    refresh_token = await repository.get_refresh_token_by_hash(hash_token(raw_refresh_token), db)
    if refresh_token is None or refresh_token.revoked_at is not None:
        return

    user = await repository.get_user_by_id(refresh_token.user_id, db)
    async with transaction(db):
        await repository.revoke_refresh_token(refresh_token, db=db)
        if user is not None:
            await audit_facade.record_event(
                RecordAuditEvent(
                    org_id=user.org_id,
                    actor_user_id=user.id,
                    event="auth.logout",
                    target_type="user",
                    target_id=user.id,
                ),
                db,
            )


async def verify_access_token(token: str, db: AsyncSession) -> AuthenticatedUser:
    try:
        claims = decode_access_token(token)
        user_id = UUID(claims["sub"])
        user = await repository.get_user_by_id(user_id, db)
    except (KeyError, SecurityError, ValueError) as exc:
        raise InvalidAccessTokenError from exc

    if user is None or not user.is_active:
        raise InvalidAccessTokenError

    return AuthenticatedUser(
        id=user.id,
        org_id=user.org_id,
        team_id=user.team_id,
        email=user.email,
        role=user.role,
    )


async def _issue_refresh_token(user: User, db: AsyncSession) -> tuple[str, RefreshToken]:
    raw_refresh_token = secrets.token_urlsafe(48)
    refresh_token = await repository.create_refresh_token(
        user_id=user.id,
        token_hash=hash_token(raw_refresh_token),
        expires_at=datetime.now(UTC) + REFRESH_TOKEN_TTL,
        db=db,
    )
    return raw_refresh_token, refresh_token


def _access_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id=user.id, org_id=user.org_id, role=user.role),
    )


async def _record_failed_login(email: str, user: User | None, db: AsyncSession) -> None:
    if user is None:
        # No org exists for an unknown email with the current audit schema.
        return

    await audit_facade.record_event(
        RecordAuditEvent(
            org_id=user.org_id,
            actor_user_id=user.id,
            event="auth.login_failed",
            target_type="user",
            target_id=user.id,
            event_metadata={"email": email},
        ),
        db,
    )


async def _handle_refresh_reuse(refresh_token: RefreshToken, db: AsyncSession) -> None:
    if refresh_token.replaced_by_token_id is None:
        return
    replacement = await db.get(RefreshToken, refresh_token.replaced_by_token_id)
    if replacement is not None and replacement.revoked_at is None:
        async with transaction(db):
            await repository.revoke_refresh_token(replacement, db=db)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
