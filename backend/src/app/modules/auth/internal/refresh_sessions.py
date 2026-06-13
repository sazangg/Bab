from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_secret_token, hash_token
from app.modules.auth.errors import InvalidRefreshTokenError, RefreshTokenReuseError
from app.modules.auth.internal.models import RefreshSession

REFRESH_SESSION_TTL = timedelta(days=30)

logger = structlog.get_logger(__name__)


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
    if not raw_token:
        raise InvalidRefreshTokenError
    token_hash = hash_token(raw_token)
    session = await db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash))
    if session is None:
        raise InvalidRefreshTokenError
    now = datetime.now(UTC)
    # Reuse-after-rotation detection: a token whose session is already revoked is
    # being replayed. Signal it without mutating here — the caller revokes the whole
    # rotation chain in its own committed transaction (raising here would otherwise
    # roll the revocation back).
    if session.revoked_at is not None:
        raise RefreshTokenReuseError
    if _is_past(session.expires_at):
        raise InvalidRefreshTokenError
    # Atomically claim the session for rotation. The `revoked_at IS NULL` guard means
    # only one of N concurrent refreshes flips the row, so a stolen-token race (or a
    # benign double-submit) cannot mint two independently-valid sessions.
    claimed = await db.execute(
        update(RefreshSession)
        .where(RefreshSession.id == session.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now, last_used_at=now)
    )
    if claimed.rowcount != 1:
        raise InvalidRefreshTokenError
    new_raw_token = generate_secret_token()
    new_session = RefreshSession(
        user_id=session.user_id,
        org_id=session.org_id,
        token_hash=hash_token(new_raw_token),
        expires_at=now + expires_delta,
    )
    db.add(new_session)
    await db.flush()
    # Keep the ORM-loaded row consistent with the conditional UPDATE and link the
    # rotation chain for reuse detection.
    session.revoked_at = now
    session.last_used_at = now
    session.replaced_by_session_id = new_session.id
    await db.flush()
    return new_session, new_raw_token


async def revoke_refresh_session_family(*, raw_token: str | None, db: AsyncSession) -> None:
    """Revoke a replayed token's entire rotation chain (defensive reuse response)."""
    if not raw_token:
        return
    session = await db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(raw_token))
    )
    if session is None:
        return
    logger.warning(
        "refresh_token_reuse_detected",
        session_id=str(session.id),
        user_id=str(session.user_id),
        org_id=str(session.org_id),
    )
    now = datetime.now(UTC)
    current: RefreshSession | None = session
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.revoked_at is None:
            current.revoked_at = now
            current.last_used_at = now
        next_id = current.replaced_by_session_id
        current = (
            await db.scalar(select(RefreshSession).where(RefreshSession.id == next_id))
            if next_id is not None
            else None
        )
    await db.flush()


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


def _is_past(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value < datetime.now(UTC)
