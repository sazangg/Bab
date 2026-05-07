from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import RefreshToken, User


async def get_user_by_email(email: str, db: AsyncSession) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def get_user_by_id(user_id, db: AsyncSession) -> User | None:
    return await db.get(User, user_id)


async def create_refresh_token(
    *,
    user_id,
    token_hash: str,
    expires_at: datetime,
    db: AsyncSession,
) -> RefreshToken:
    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(refresh_token)
    await db.flush()
    return refresh_token


async def get_refresh_token_by_hash(token_hash: str, db: AsyncSession) -> RefreshToken | None:
    return await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))


async def revoke_refresh_token(
    refresh_token: RefreshToken,
    *,
    db: AsyncSession,
    replaced_by_token_id=None,
) -> None:
    refresh_token.revoked_at = datetime.now(UTC)
    refresh_token.replaced_by_token_id = replaced_by_token_id
    await db.flush()
