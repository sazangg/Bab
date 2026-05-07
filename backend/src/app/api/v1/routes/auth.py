from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth import facade
from app.modules.auth.errors import InvalidCredentialsError, InvalidRefreshTokenError
from app.modules.auth.schemas import LoginRequest, TokenResponse

REFRESH_COOKIE_NAME = "bab_refresh_token"

router = APIRouter(prefix="/auth", tags=["auth"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]


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


def _set_refresh_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=value,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/api/v1/auth",
        max_age=60 * 60 * 24 * 30,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
    )
