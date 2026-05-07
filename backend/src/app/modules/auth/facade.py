from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal import service
from app.modules.auth.schemas import AuthenticatedUser, LoginRequest, TokenResponse


async def login(payload: LoginRequest, db: AsyncSession) -> tuple[TokenResponse, str]:
    return await service.login(payload, db)


async def refresh(raw_refresh_token: str | None, db: AsyncSession) -> tuple[TokenResponse, str]:
    return await service.refresh(raw_refresh_token, db)


async def logout(raw_refresh_token: str | None, db: AsyncSession) -> None:
    await service.logout(raw_refresh_token, db)


async def verify_access_token(token: str, db: AsyncSession) -> AuthenticatedUser:
    return await service.verify_access_token(token, db)
