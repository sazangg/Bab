import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityError, create_access_token, decode_access_token
from app.modules.audit import facade as audit_facade
from app.modules.audit.schemas import RecordAuditEvent
from app.modules.auth.errors import (
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import AuthenticatedUser, LoginRequest, TokenResponse

MOCK_ADMIN_ID = UUID("00000000-0000-4000-8000-000000000001")
REFRESH_TOKEN_TTL = timedelta(days=30)


async def login(payload: LoginRequest, db: AsyncSession) -> tuple[TokenResponse, str]:
    if (
        payload.email != settings.default_admin_email
        or payload.password != settings.default_admin_password
    ):
        raise InvalidCredentialsError

    principal = await get_default_principal(db)
    raw_refresh_token = _create_refresh_token(principal)
    await audit_facade.record_event(
        RecordAuditEvent(
            org_id=principal.org_id,
            actor_user_id=principal.id,
            event="auth.login_success",
            target_type="mock_admin",
            target_id=principal.id,
        ),
        db,
    )
    return _access_response(principal), raw_refresh_token


async def refresh(raw_refresh_token: str | None, db: AsyncSession) -> tuple[TokenResponse, str]:
    if not raw_refresh_token:
        raise InvalidRefreshTokenError

    try:
        claims = decode_access_token(raw_refresh_token, expected_type="refresh")
    except SecurityError as exc:
        raise InvalidRefreshTokenError from exc

    if claims.get("sub") != str(MOCK_ADMIN_ID):
        raise InvalidRefreshTokenError

    principal = await get_default_principal(db)
    return _access_response(principal), _create_refresh_token(principal)


async def logout(raw_refresh_token: str | None, db: AsyncSession) -> None:
    if not raw_refresh_token:
        return

    principal = await get_default_principal(db)
    await audit_facade.record_event(
        RecordAuditEvent(
            org_id=principal.org_id,
            actor_user_id=principal.id,
            event="auth.logout",
            target_type="mock_admin",
            target_id=principal.id,
        ),
        db,
    )


async def verify_access_token(token: str, db: AsyncSession) -> AuthenticatedUser:
    try:
        claims = decode_access_token(token)
    except SecurityError as exc:
        raise InvalidAccessTokenError from exc

    if claims.get("sub") != str(MOCK_ADMIN_ID):
        raise InvalidAccessTokenError

    return await get_default_principal(db)


async def get_default_principal(db: AsyncSession) -> AuthenticatedUser:
    org = await db.scalar(
        select(Organization).where(Organization.slug == _default_org_slug())
    )
    team = None
    if org is not None:
        team = await db.scalar(
            select(Team).where(
                Team.org_id == org.id,
                Team.slug == _default_team_slug(),
            )
        )

    if org is None or team is None:
        raise InvalidAccessTokenError

    return AuthenticatedUser(
        id=MOCK_ADMIN_ID,
        org_id=org.id,
        team_id=team.id,
        email=settings.default_admin_email,
        role="super_admin",
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


def _default_org_slug() -> str:
    return _slugify(settings.default_organization_name)


def _default_team_slug() -> str:
    return _slugify(settings.default_team_name)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "default"
