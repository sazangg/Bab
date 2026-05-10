import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.auth.internal.models import Organization, User


async def _create_user(db_session: AsyncSession, *, slug: str, role: str = "super_admin") -> User:
    org = Organization(name=f"Org {slug}", slug=slug)
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{slug}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_super_admin_can_manage_limit_policies(app_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session, slug="limits-admin")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/api/v1/limit-policies",
            headers=_auth_headers(user),
            json={
                "scope_type": "org",
                "scope_id": str(user.org_id),
                "metric": "request_count",
                "window": "minute",
                "limit_value": 10,
            },
        )
        policy_id = create_response.json()["id"]
        list_response = await client.get("/api/v1/limit-policies", headers=_auth_headers(user))
        update_response = await client.patch(
            f"/api/v1/limit-policies/{policy_id}",
            headers=_auth_headers(user),
            json={"limit_value": 20, "is_active": False},
        )
        delete_response = await client.delete(
            f"/api/v1/limit-policies/{policy_id}",
            headers=_auth_headers(user),
        )

    assert create_response.status_code == 201
    assert create_response.json()["limit_value"] == 10
    assert list_response.status_code == 200
    assert [policy["id"] for policy in list_response.json()] == [policy_id]
    assert update_response.status_code == 200
    assert update_response.json()["limit_value"] == 20
    assert update_response.json()["is_active"] is False
    assert delete_response.status_code == 204


@pytest.mark.asyncio
async def test_limit_policy_validation_rejects_invalid_shape(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="limits-validation")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/limit-policies",
            headers=_auth_headers(user),
            json={
                "scope_type": "provider_model",
                "scope_id": str(user.org_id),
                "metric": "token_count",
                "window": "day",
                "limit_value": 100,
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "provider_model limit policies require scope_value"


@pytest.mark.asyncio
async def test_team_manager_cannot_create_limit_policy(
    app_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, slug="limits-manager", role="team_manager")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/limit-policies",
            headers=_auth_headers(user),
            json={
                "scope_type": "org",
                "scope_id": str(user.org_id),
                "metric": "request_count",
                "window": "minute",
                "limit_value": 10,
            },
        )

    assert response.status_code == 403
