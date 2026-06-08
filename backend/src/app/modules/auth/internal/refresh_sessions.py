from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_secret_token, hash_token
from app.modules.auth.errors import InvalidRefreshTokenError
from app.modules.auth.internal.models import RefreshSession

REFRESH_SESSION_TTL = timedelta(days=30)


async def create_refresh_session(
    *,
    user_id: UUID,
    org_id: UUID,
    db: AsyncSession,
    expires_delta: timedelta = REFRESH_SESSION_TTL,
) -> str:
    raw_token = generate_secret_token()
    session = RefreshSession(
        user_id=user_id,
        org_id=org_id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + expires_delta,
    )
    db.add(session)
    await db.flush()
    return raw_token


async def rotate_refresh_session(
    *,
    raw_token: str | None,
    db: AsyncSession,
    expires_delta: timedelta = REFRESH_SESSION_TTL,
) -> tuple[RefreshSession, str]:
    session = await _active_session(raw_token=raw_token, db=db)
    now = datetime.now(UTC)
    new_raw_token = generate_secret_token()
    new_session = RefreshSession(
        user_id=session.user_id,
        org_id=session.org_id,
        token_hash=hash_token(new_raw_token),
        expires_at=now + expires_delta,
    )
    db.add(new_session)
    await db.flush()
    session.revoked_at = now
    session.last_used_at = now
    session.replaced_by_session_id = new_session.id
    await db.flush()
    return new_session, new_raw_token


async def revoke_refresh_session(
    *,
    raw_token: str | None,
    db: AsyncSession,
) -> RefreshSession | None:
    if not raw_token:
        return None
    session = await db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(raw_token))
    )
    if session is None or session.revoked_at is not None:
        return None
    session.revoked_at = datetime.now(UTC)
    session.last_used_at = session.revoked_at
    await db.flush()
    return session


async def _active_session(*, raw_token: str | None, db: AsyncSession) -> RefreshSession:
    if not raw_token:
        raise InvalidRefreshTokenError
    session = await db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(raw_token))
    )
    if session is None or session.revoked_at is not None or _is_past(session.expires_at):
        raise InvalidRefreshTokenError
    return session


def _is_past(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value < datetime.now(UTC)
