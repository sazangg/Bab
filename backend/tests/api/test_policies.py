import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import bootstrap
from app.core.database import Scope
from app.modules.auth.internal.models import Organization, Team
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import (
    AddCredentialPoolCredentialRequest,
    CreateCredentialPoolRequest,
    CreateModelOfferingRequest,
    CreateProviderCredentialRequest,
    CreateProviderRequest,
)


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_provider_fixture(db_session: AsyncSession, *, name: str):
    org = await db_session.scalar(select(Organization))
    assert org is not None
    actor = AuthenticatedUser(
        id=bootstrap.DEFAULT_ADMIN_USER_ID,
        org_id=org.id,
        email="admin@example.com",
        role="org_owner",
        permissions=["*"],
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name=name, base_url=f"https://{name}.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    pool = await providers_facade.create_credential_pool(
        provider_id=provider.id,
        payload=CreateCredentialPoolRequest(name="Primary"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Credential", api_key="secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    await providers_facade.add_credential_pool_credential(
        provider_id=provider.id,
        pool_id=pool.id,
        payload=AddCredentialPoolCredentialRequest(provider_credential_id=credential.id),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    model = await providers_facade.create_model_offering(
        provider_id=provider.id,
        payload=CreateModelOfferingRequest(provider_model_name=f"{name}-model"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    return provider, pool, model


async def _create_team_fixture(db_session: AsyncSession, *, name: str) -> Team:
    org = await db_session.scalar(select(Organization))
    assert org is not None
    team = Team(org_id=org.id, name=name, slug=name.lower().replace(" ", "-"))
    db_session.add(team)
    await db_session.commit()
    await db_session.refresh(team)
    return team


@pytest.mark.asyncio
async def test_limit_policy_can_be_created_and_assigned_to_org(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client)
        policy_response = await client.post(
            "/api/v1/policies/limits",
            headers=headers,
            json={
                "name": "Org monthly budget",
                "rules": [
                    {
                        "name": "Monthly budget",
                        "limit_type": "budget_cents",
                        "limit_value": 500_000,
                        "interval_unit": "month",
                    }
                ],
            },
        )
        assert policy_response.status_code == 201
        policy_id = policy_response.json()["id"]

        assignment_response = await client.post(
            "/api/v1/policies/assignments",
            headers=headers,
            json={
                "policy_type": "limit",
                "limit_policy_id": policy_id,
                "scope_type": "org",
            },
        )
        assert assignment_response.status_code == 201

        list_response = await client.get("/api/v1/policies/limits", headers=headers)

    assert list_response.status_code == 200
    assert list_response.json()[0]["name"] == "Org monthly budget"


@pytest.mark.asyncio
async def test_viewer_can_read_but_not_create_policies(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        admin_headers = await _login(client)
        create_member = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "viewer@example.com",
                "password": "viewer-password",
                "role": "org_viewer",
            },
        )
        assert create_member.status_code == 201
        viewer_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "viewer-password"},
        )
        viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}

        read_response = await client.get("/api/v1/policies/access", headers=viewer_headers)
        write_response = await client.post(
            "/api/v1/policies/limits",
            headers=viewer_headers,
            json={
                "name": "Viewer budget",
                "rules": [
                    {
                        "name": "Monthly budget",
                        "limit_type": "budget_cents",
                        "limit_value": 500_000,
                        "interval_unit": "month",
                    }
                ],
            },
        )

    assert read_response.status_code == 200
    assert write_response.status_code == 403


@pytest.mark.asyncio
async def test_scoped_admin_can_create_owned_policy_only_for_current_scope(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    default_team = await _create_team_fixture(db_session, name="Policy Team")
    other_team = Team(org_id=default_team.org_id, name="Other Team", slug="other-team")
    db_session.add(other_team)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        admin_headers = await _login(client)
        first_member = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "team-admin@example.com",
                "password": "team-admin-password",
                "role": "org_member",
            },
        )
        second_member = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "other-admin@example.com",
                "password": "other-admin-password",
                "role": "org_member",
            },
        )
        await client.post(
            f"/api/v1/teams/{default_team.id}/members",
            headers=admin_headers,
            json={"user_id": first_member.json()["user_id"], "role": "team_admin"},
        )
        await client.post(
            f"/api/v1/teams/{other_team.id}/members",
            headers=admin_headers,
            json={"user_id": second_member.json()["user_id"], "role": "team_admin"},
        )
        scoped_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "team-admin@example.com", "password": "team-admin-password"},
        )
        other_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "other-admin@example.com", "password": "other-admin-password"},
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

        create_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "limit",
                "scope_type": "team",
                "team_id": str(default_team.id),
                "limit_policy": {
                    "name": "Team scoped requests",
                    "rules": [
                        {
                            "name": "Daily requests",
                            "limit_type": "requests",
                            "limit_value": 100,
                            "interval_unit": "day",
                        }
                    ],
                },
            },
        )
        assert create_response.status_code == 201
        policy = create_response.json()["limit_policy"]
        assignment = create_response.json()["assignment"]

        reuse_response = await client.post(
            "/api/v1/policies/assignments",
            headers=scoped_headers,
            json={
                "policy_type": "limit",
                "limit_policy_id": policy["id"],
                "scope_type": "team",
                "team_id": str(other_team.id),
            },
        )
        visible_to_other = await client.get("/api/v1/policies/limits", headers=other_headers)
        other_reuse_response = await client.post(
            "/api/v1/policies/assignments",
            headers=other_headers,
            json={
                "policy_type": "limit",
                "limit_policy_id": policy["id"],
                "scope_type": "team",
                "team_id": str(other_team.id),
            },
        )

    assert policy["owning_scope_type"] == "team"
    assert policy["owning_team_id"] == str(default_team.id)
    assert assignment["team_id"] == str(default_team.id)
    assert reuse_response.status_code == 403
    assert other_reuse_response.status_code == 400
    assert visible_to_other.status_code == 200
    assert visible_to_other.json() == []


@pytest.mark.asyncio
async def test_scoped_admin_can_list_and_assign_org_created_policy(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    default_team = await _create_team_fixture(db_session, name="Reusable Policy Team")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        admin_headers = await _login(client)
        policy_response = await client.post(
            "/api/v1/policies/limits",
            headers=admin_headers,
            json={
                "name": "Reusable org policy",
                "rules": [
                    {
                        "name": "Daily requests",
                        "limit_type": "requests",
                        "limit_value": 100,
                        "interval_unit": "day",
                    }
                ],
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "policy-team-admin@example.com",
                "password": "team-admin-password",
                "role": "org_member",
            },
        )
        await client.post(
            f"/api/v1/teams/{default_team.id}/members",
            headers=admin_headers,
            json={"user_id": member_response.json()["user_id"], "role": "team_admin"},
        )
        scoped_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "policy-team-admin@example.com", "password": "team-admin-password"},
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        list_response = await client.get("/api/v1/policies/limits", headers=scoped_headers)
        assignment_response = await client.post(
            "/api/v1/policies/assignments",
            headers=scoped_headers,
            json={
                "policy_type": "limit",
                "limit_policy_id": policy_response.json()["id"],
                "scope_type": "team",
                "team_id": str(default_team.id),
            },
        )

    assert policy_response.status_code == 201
    assert list_response.status_code == 200
    assert [item["name"] for item in list_response.json()] == ["Reusable org policy"]
    assert assignment_response.status_code == 201


@pytest.mark.asyncio
async def test_scoped_access_policy_creation_cannot_widen_inherited_access(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    default_team = await _create_team_fixture(db_session, name="Access Narrowing Team")
    allowed_provider, allowed_pool, allowed_model = await _create_provider_fixture(
        db_session, name="allowed"
    )
    wider_provider, wider_pool, wider_model = await _create_provider_fixture(
        db_session, name="wider"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        admin_headers = await _login(client)
        parent_policy = await client.post(
            "/api/v1/policies/access",
            headers=admin_headers,
            json={
                "name": "Org access",
                "routes": [
                    {
                        "provider_id": str(allowed_provider.id),
                        "credential_pool_id": str(allowed_pool.id),
                        "model_offering_ids": [str(allowed_model.id)],
                    }
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "access_policy_id": parent_policy.json()["id"],
                "scope_type": "org",
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "access-team-admin@example.com",
                "password": "team-admin-password",
                "role": "org_member",
            },
        )
        await client.post(
            f"/api/v1/teams/{default_team.id}/members",
            headers=admin_headers,
            json={"user_id": member_response.json()["user_id"], "role": "team_admin"},
        )
        scoped_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "access-team-admin@example.com", "password": "team-admin-password"},
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        wider_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "access",
                "scope_type": "team",
                "team_id": str(default_team.id),
                "access_policy": {
                    "name": "Wider team access",
                    "routes": [
                        {
                            "provider_id": str(wider_provider.id),
                            "credential_pool_id": str(wider_pool.id),
                            "model_offering_ids": [str(wider_model.id)],
                        }
                    ],
                },
            },
        )
        narrowed_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "access",
                "scope_type": "team",
                "team_id": str(default_team.id),
                "access_policy": {
                    "name": "Narrow team access",
                    "routes": [
                        {
                            "provider_id": str(allowed_provider.id),
                            "credential_pool_id": str(allowed_pool.id),
                            "model_offering_ids": [str(allowed_model.id)],
                        }
                    ],
                },
            },
        )

    assert parent_policy.status_code == 201
    assert wider_response.status_code == 400
    assert narrowed_response.status_code == 201


@pytest.mark.asyncio
async def test_access_policy_creation_payload_accepts_multiple_routes(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    first_provider, first_pool, first_model = await _create_provider_fixture(
        db_session, name="route-a"
    )
    second_provider, second_pool, second_model = await _create_provider_fixture(
        db_session, name="route-b"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client)
        response = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Multi-route access",
                "routes": [
                    {
                        "provider_id": str(first_provider.id),
                        "credential_pool_id": str(first_pool.id),
                        "model_offering_ids": [str(first_model.id)],
                        "priority": 10,
                    },
                    {
                        "provider_id": str(second_provider.id),
                        "credential_pool_id": str(second_pool.id),
                        "model_offering_ids": [str(second_model.id)],
                        "priority": 20,
                    },
                ],
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Multi-route access"
    assert [route["priority"] for route in body["routes"]] == [10, 20]
    assert {route["provider_id"] for route in body["routes"]} == {
        str(first_provider.id),
        str(second_provider.id),
    }


@pytest.mark.asyncio
async def test_scoped_access_policy_creation_supports_multiple_narrowed_routes(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    team = await _create_team_fixture(db_session, name="Scoped Multi Route Team")
    first_provider, first_pool, first_model = await _create_provider_fixture(
        db_session, name="scoped-route-a"
    )
    second_provider, second_pool, second_model = await _create_provider_fixture(
        db_session, name="scoped-route-b"
    )
    wider_provider, wider_pool, wider_model = await _create_provider_fixture(
        db_session, name="scoped-route-c"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        admin_headers = await _login(client)
        parent_policy = await client.post(
            "/api/v1/policies/access",
            headers=admin_headers,
            json={
                "name": "Org multi-route parent",
                "routes": [
                    {
                        "provider_id": str(first_provider.id),
                        "credential_pool_id": str(first_pool.id),
                        "model_offering_ids": [str(first_model.id)],
                    },
                    {
                        "provider_id": str(second_provider.id),
                        "credential_pool_id": str(second_pool.id),
                        "model_offering_ids": [str(second_model.id)],
                    },
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "access_policy_id": parent_policy.json()["id"],
                "scope_type": "org",
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "multi-route-team-admin@example.com",
                "password": "team-admin-password",
                "role": "org_member",
            },
        )
        await client.post(
            f"/api/v1/teams/{team.id}/members",
            headers=admin_headers,
            json={"user_id": member_response.json()["user_id"], "role": "team_admin"},
        )
        scoped_login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "multi-route-team-admin@example.com",
                "password": "team-admin-password",
            },
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        narrowed_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "access",
                "scope_type": "team",
                "team_id": str(team.id),
                "access_policy": {
                    "name": "Team multi-route child",
                    "routes": [
                        {
                            "provider_id": str(first_provider.id),
                            "credential_pool_id": str(first_pool.id),
                            "model_offering_ids": [str(first_model.id)],
                        },
                        {
                            "provider_id": str(second_provider.id),
                            "credential_pool_id": str(second_pool.id),
                            "model_offering_ids": [str(second_model.id)],
                        },
                    ],
                },
            },
        )
        wider_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "access",
                "scope_type": "team",
                "team_id": str(team.id),
                "access_policy": {
                    "name": "Team widened child",
                    "routes": [
                        {
                            "provider_id": str(first_provider.id),
                            "credential_pool_id": str(first_pool.id),
                            "model_offering_ids": [str(first_model.id)],
                        },
                        {
                            "provider_id": str(wider_provider.id),
                            "credential_pool_id": str(wider_pool.id),
                            "model_offering_ids": [str(wider_model.id)],
                        },
                    ],
                },
            },
        )

    assert parent_policy.status_code == 201
    assert narrowed_response.status_code == 201
    assert len(narrowed_response.json()["access_policy"]["routes"]) == 2
    assert wider_response.status_code == 400
