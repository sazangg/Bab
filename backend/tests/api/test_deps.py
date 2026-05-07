from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_scope, require_role
from app.core.database import Scope
from app.core.security import create_access_token, hash_password
from app.modules.auth.internal.models import Organization, User
from app.modules.auth.schemas import AuthenticatedUser


async def _create_user(
    db_session: AsyncSession,
    *,
    role: str = "super_admin",
    is_active: bool = True,
) -> User:
    org = Organization(name=f"Org {role}", slug=f"org-{role}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{role}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _add_test_routes(app_client) -> None:
    router = APIRouter()

    @router.get("/test/me")
    async def me(user: Annotated[AuthenticatedUser, Depends(get_current_user)]):
        return {"user_id": str(user.id), "role": user.role}

    @router.get("/test/admin")
    async def admin(user: Annotated[AuthenticatedUser, Depends(require_role("super_admin"))]):
        return {"user_id": str(user.id)}

    @router.get("/test/scope")
    async def scoped(scope: Annotated[Scope, Depends(get_scope)]):
        return {"org_id": str(scope.org_id), "project_id": scope.project_id}

    app_client.include_router(router)


@pytest.mark.asyncio
async def test_get_current_user_accepts_valid_access_token(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    _add_test_routes(app_client)
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user.id), "role": "super_admin"}


@pytest.mark.asyncio
async def test_get_current_user_rejects_missing_or_invalid_token(app_client) -> None:
    _add_test_routes(app_client)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        missing_response = await client.get("/test/me")
        invalid_response = await client.get(
            "/test/me",
            headers={"Authorization": "Bearer invalid"},
        )

    assert missing_response.status_code == 401
    assert invalid_response.status_code == 401


@pytest.mark.asyncio
async def test_require_role_enforces_allowed_roles(app_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session, role="team_manager")
    _add_test_routes(app_client)
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test/admin", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_scope_uses_current_user_org(app_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    _add_test_routes(app_client)
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test/scope", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"org_id": str(user.org_id), "project_id": None}
