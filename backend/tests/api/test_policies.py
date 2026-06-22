from uuid import uuid4

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
    CreateProviderCredentialRequest,
    CreateProviderModelOfferingRequest,
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
        payload=CreateProviderModelOfferingRequest(provider_model_name=f"{name}-model"),
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


def _public_model_payload(provider_id, pool_id, model_id, *, name: str | None = None, priority=100):
    return {
        "public_model_name": name or str(model_id),
        "routing_mode": "single_route",
        "candidates": [
            {
                "provider_id": str(provider_id),
                "credential_pool_id": str(pool_id),
                "model_offering_id": str(model_id),
                "priority": priority,
            }
        ],
    }


@pytest.mark.asyncio
async def test_policy_simulation_rejects_invalid_draft_before_target_lookup(
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
        response = await client.post(
            "/api/v1/policies/simulations",
            headers=headers,
            json={
                "target": {"virtual_key_id": str(uuid4())},
                "requested_model": "fast",
                "gateway_endpoint": "chat_completions",
                "drafts": [
                    {
                        "kind": "limit",
                        "operation": "add_policy",
                        "assignment": {"scope_type": "org"},
                        "limit_policy": {
                            "name": "Invalid draft",
                            "rules": [
                                {
                                    "name": "Invalid matcher",
                                    "limit_type": "requests",
                                    "limit_value": 1,
                                    "interval_unit": "day",
                                    "matchers": [
                                        {
                                            "dimension": "not_a_dimension",
                                            "operator": "eq",
                                            "value_json": "x",
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ],
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid policy simulation draft"


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
        policy_id = policy_response.json()["policy_id"]

        assignment_response = await client.post(
            "/api/v1/policies/assignments",
            headers=headers,
            json={
                "policy_type": "limit",
                "policy_id": policy_id,
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
                "policy_id": policy["policy_id"],
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
                "policy_id": policy["policy_id"],
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
                "policy_id": policy_response.json()["policy_id"],
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
                "public_models": [
                    _public_model_payload(allowed_provider.id, allowed_pool.id, allowed_model.id)
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "policy_id": parent_policy.json()["policy_id"],
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
                    "public_models": [
                        _public_model_payload(wider_provider.id, wider_pool.id, wider_model.id)
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
                    "public_models": [
                        _public_model_payload(
                            allowed_provider.id, allowed_pool.id, allowed_model.id
                        )
                    ],
                },
            },
        )

    assert parent_policy.status_code == 201
    assert wider_response.status_code == 400
    assert narrowed_response.status_code == 201


@pytest.mark.asyncio
async def test_scoped_admin_can_update_owned_limit_policy_but_not_org_policy(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    team = await _create_team_fixture(db_session, name="Limit Policy Editors")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        admin_headers = await _login(client)
        org_policy = await client.post(
            "/api/v1/policies/limits",
            headers=admin_headers,
            json={
                "name": "Org owned limits",
                "rules": [
                    {
                        "name": "Org daily requests",
                        "limit_type": "requests",
                        "limit_value": 1000,
                        "interval_unit": "day",
                    }
                ],
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "limit-policy-editor@example.com",
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
                "email": "limit-policy-editor@example.com",
                "password": "team-admin-password",
            },
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        create_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "limit",
                "scope_type": "team",
                "team_id": str(team.id),
                "limit_policy": {
                    "name": "Team owned limits",
                    "rules": [
                        {
                            "name": "Team daily requests",
                            "limit_type": "requests",
                            "limit_value": 100,
                            "interval_unit": "day",
                        }
                    ],
                },
            },
        )
        policy = create_response.json()["limit_policy"]
        rule = policy["rules"][0]

        detail_response = await client.get(
            f"/api/v1/policies/limits/{policy['id']}", headers=scoped_headers
        )
        update_response = await client.patch(
            f"/api/v1/policies/limits/{policy['id']}",
            headers=scoped_headers,
            json={"name": "Team owned limits updated", "is_active": False},
        )
        rule_update_response = await client.patch(
            f"/api/v1/policies/limits/rules/{rule['id']}",
            headers=scoped_headers,
            json={"limit_value": 50, "is_active": False},
        )
        org_update_response = await client.patch(
            f"/api/v1/policies/limits/{org_policy.json()['id']}",
            headers=scoped_headers,
            json={"name": "Scoped user cannot rename org policy"},
        )

    assert org_policy.status_code == 201
    assert create_response.status_code == 201
    assert detail_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Team owned limits updated"
    assert update_response.json()["is_active"] is False
    assert rule_update_response.status_code == 200
    assert rule_update_response.json()["limit_value"] == 50
    assert rule_update_response.json()["is_active"] is False
    assert org_update_response.status_code == 403


@pytest.mark.asyncio
async def test_scoped_admin_route_update_cannot_widen_inherited_access(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    team = await _create_team_fixture(db_session, name="Route Policy Editors")
    allowed_provider, allowed_pool, allowed_model = await _create_provider_fixture(
        db_session, name="route-update-allowed"
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
                "name": "Org route parent",
                "public_models": [
                    _public_model_payload(allowed_provider.id, allowed_pool.id, allowed_model.id)
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "policy_id": parent_policy.json()["policy_id"],
                "scope_type": "org",
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "route-policy-editor@example.com",
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
                "email": "route-policy-editor@example.com",
                "password": "team-admin-password",
            },
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        create_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "access",
                "scope_type": "team",
                "team_id": str(team.id),
                "access_policy": {
                    "name": "Team route child",
                    "public_models": [
                        _public_model_payload(
                            allowed_provider.id, allowed_pool.id, allowed_model.id
                        )
                    ],
                },
            },
        )
        policy = create_response.json()["access_policy"]

        detail_response = await client.get(
            f"/api/v1/policies/access/{policy['id']}", headers=scoped_headers
        )
        policy_update_response = await client.patch(
            f"/api/v1/policies/access/{policy['id']}",
            headers=scoped_headers,
            json={"description": "Team scoped public model policy"},
        )
        org_update_response = await client.patch(
            f"/api/v1/policies/access/{parent_policy.json()['id']}",
            headers=scoped_headers,
            json={"description": "Scoped user cannot edit org parent"},
        )

    assert parent_policy.status_code == 201
    assert create_response.status_code == 201
    assert detail_response.status_code == 200
    assert policy_update_response.status_code == 200
    assert policy_update_response.json()["description"] == "Team scoped public model policy"
    assert org_update_response.status_code == 403


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
                "name": "Multi-public-model access",
                "public_models": [
                    _public_model_payload(
                        first_provider.id,
                        first_pool.id,
                        first_model.id,
                        name=first_model.provider_model_name,
                        priority=10,
                    ),
                    _public_model_payload(
                        second_provider.id,
                        second_pool.id,
                        second_model.id,
                        name=second_model.provider_model_name,
                        priority=20,
                    ),
                ],
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Multi-public-model access"
    candidates = [public_model["candidates"][0] for public_model in body["public_models"]]
    assert [candidate["priority"] for candidate in candidates] == [10, 20]
    assert {candidate["provider_id"] for candidate in candidates} == {
        str(first_provider.id),
        str(second_provider.id),
    }
    assert {public_model["public_model_name"] for public_model in body["public_models"]} == {
        first_model.provider_model_name,
        second_model.provider_model_name,
    }


@pytest.mark.asyncio
async def test_access_policy_public_models_are_created_and_returned(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    provider, pool, model = await _create_provider_fixture(db_session, name="public-model")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client)
        response = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Logical models",
                "public_models": [
                    {
                        "public_model_name": "chat-large",
                        "routing_mode": "ordered_fallback",
                        "fallback_on": ["timeout", "provider_5xx"],
                        "candidates": [
                            {
                                "provider_id": str(provider.id),
                                "credential_pool_id": str(pool.id),
                                "model_offering_id": str(model.id),
                                "priority": 10,
                            }
                        ],
                    }
                ],
            },
        )
        duplicate_response = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Duplicate logical models",
                "public_models": [
                    {
                        "public_model_name": "chat-large",
                        "candidates": [
                            {
                                "provider_id": str(provider.id),
                                "credential_pool_id": str(pool.id),
                                "model_offering_id": str(model.id),
                            }
                        ],
                    },
                    {
                        "public_model_name": "chat-large",
                        "candidates": [
                            {
                                "provider_id": str(provider.id),
                                "credential_pool_id": str(pool.id),
                                "model_offering_id": str(model.id),
                            }
                        ],
                    },
                ],
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["public_models"][0]["public_model_name"] == "chat-large"
    assert body["public_models"][0]["routing_mode"] == "ordered_fallback"
    assert body["public_models"][0]["fallback_on"] == ["timeout", "provider_5xx"]
    assert body["public_models"][0]["candidates"][0]["model_offering_id"] == str(model.id)
    assert duplicate_response.status_code == 400


@pytest.mark.asyncio
async def test_access_policy_update_replaces_public_models(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    first_provider, first_pool, first_model = await _create_provider_fixture(
        db_session, name="initial-public-model"
    )
    second_provider, second_pool, second_model = await _create_provider_fixture(
        db_session, name="replacement-public-model"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client)
        create_response = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Editable logical models",
                "public_models": [
                    _public_model_payload(
                        first_provider.id,
                        first_pool.id,
                        first_model.id,
                        name="chat-initial",
                    )
                ],
            },
        )
        policy_id = create_response.json()["id"]
        update_response = await client.patch(
            f"/api/v1/policies/access/{policy_id}",
            headers=headers,
            json={
                "name": "Editable logical models",
                "public_models": [
                    _public_model_payload(
                        second_provider.id,
                        second_pool.id,
                        second_model.id,
                        name="chat-replacement",
                    )
                ],
            },
        )

    assert create_response.status_code == 201
    assert update_response.status_code == 200
    public_models = update_response.json()["public_models"]
    assert len(public_models) == 1
    assert public_models[0]["public_model_name"] == "chat-replacement"
    assert public_models[0]["candidates"][0]["model_offering_id"] == str(second_model.id)


@pytest.mark.asyncio
async def test_access_policy_assignment_rejects_same_scope_duplicate_public_model(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    provider, pool, model = await _create_provider_fixture(db_session, name="duplicate-public")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client)
        first_policy = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "First duplicate public model",
                "public_models": [
                    _public_model_payload(
                        provider.id,
                        pool.id,
                        model.id,
                        name="chat-shared",
                    )
                ],
            },
        )
        second_policy = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Second duplicate public model",
                "public_models": [
                    _public_model_payload(
                        provider.id,
                        pool.id,
                        model.id,
                        name="chat-shared",
                    )
                ],
            },
        )
        first_assignment = await client.post(
            "/api/v1/policies/assignments",
            headers=headers,
            json={
                "policy_type": "access",
                "policy_id": first_policy.json()["policy_id"],
                "scope_type": "org",
            },
        )
        duplicate_assignment = await client.post(
            "/api/v1/policies/assignments",
            headers=headers,
            json={
                "policy_type": "access",
                "policy_id": second_policy.json()["policy_id"],
                "scope_type": "org",
            },
        )

    assert first_policy.status_code == 201
    assert second_policy.status_code == 201
    assert first_assignment.status_code == 201
    assert duplicate_assignment.status_code == 409


@pytest.mark.asyncio
async def test_access_policy_update_rejects_assigned_same_scope_duplicate_public_model(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    provider, pool, model = await _create_provider_fixture(db_session, name="update-duplicate")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client)
        first_policy = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "First update duplicate",
                "public_models": [
                    _public_model_payload(provider.id, pool.id, model.id, name="chat-first")
                ],
            },
        )
        second_policy = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Second update duplicate",
                "public_models": [
                    _public_model_payload(provider.id, pool.id, model.id, name="chat-second")
                ],
            },
        )
        for policy in (first_policy, second_policy):
            assignment = await client.post(
                "/api/v1/policies/assignments",
                headers=headers,
                json={
                    "policy_type": "access",
                    "policy_id": policy.json()["policy_id"],
                    "scope_type": "org",
                },
            )
            assert assignment.status_code == 201
        update_response = await client.patch(
            f"/api/v1/policies/access/{second_policy.json()['id']}",
            headers=headers,
            json={
                "public_models": [
                    _public_model_payload(provider.id, pool.id, model.id, name="chat-first")
                ],
            },
        )

    assert first_policy.status_code == 201
    assert second_policy.status_code == 201
    assert update_response.status_code == 409


@pytest.mark.asyncio
async def test_access_policy_update_allows_duplicate_from_inactive_assigned_policy(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    provider, pool, model = await _create_provider_fixture(db_session, name="inactive-duplicate")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        headers = await _login(client)
        first_policy = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Inactive duplicate source",
                "public_models": [
                    _public_model_payload(provider.id, pool.id, model.id, name="chat-shared")
                ],
            },
        )
        second_policy = await client.post(
            "/api/v1/policies/access",
            headers=headers,
            json={
                "name": "Active duplicate target",
                "public_models": [
                    _public_model_payload(provider.id, pool.id, model.id, name="chat-second")
                ],
            },
        )
        for policy in (first_policy, second_policy):
            assignment = await client.post(
                "/api/v1/policies/assignments",
                headers=headers,
                json={
                    "policy_type": "access",
                    "policy_id": policy.json()["policy_id"],
                    "scope_type": "org",
                },
            )
            assert assignment.status_code == 201
        deactivate_response = await client.patch(
            f"/api/v1/policies/access/{first_policy.json()['id']}",
            headers=headers,
            json={"is_active": False},
        )
        update_response = await client.patch(
            f"/api/v1/policies/access/{second_policy.json()['id']}",
            headers=headers,
            json={
                "public_models": [
                    _public_model_payload(provider.id, pool.id, model.id, name="chat-shared")
                ],
            },
        )

    assert first_policy.status_code == 201
    assert second_policy.status_code == 201
    assert deactivate_response.status_code == 200
    assert update_response.status_code == 200


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
                "public_models": [
                    _public_model_payload(first_provider.id, first_pool.id, first_model.id),
                    _public_model_payload(second_provider.id, second_pool.id, second_model.id),
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "policy_id": parent_policy.json()["policy_id"],
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
                    "public_models": [
                        _public_model_payload(first_provider.id, first_pool.id, first_model.id),
                        _public_model_payload(second_provider.id, second_pool.id, second_model.id),
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
                    "public_models": [
                        _public_model_payload(first_provider.id, first_pool.id, first_model.id),
                        _public_model_payload(wider_provider.id, wider_pool.id, wider_model.id),
                    ],
                },
            },
        )

    assert parent_policy.status_code == 201
    assert narrowed_response.status_code == 201
    assert len(narrowed_response.json()["access_policy"]["public_models"]) == 2
    assert wider_response.status_code == 400


@pytest.mark.asyncio
async def test_scoped_access_policy_cannot_widen_single_route_to_ordered_public_model(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    team = await _create_team_fixture(db_session, name="Scoped Public Model Team")
    provider, pool, model = await _create_provider_fixture(db_session, name="scoped-public-model")

    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        admin_headers = await _login(client)
        parent_policy = await client.post(
            "/api/v1/policies/access",
            headers=admin_headers,
            json={
                "name": "Org single-route parent",
                "public_models": [
                    _public_model_payload(
                        provider.id, pool.id, model.id, name=model.provider_model_name
                    )
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "policy_id": parent_policy.json()["policy_id"],
                "scope_type": "org",
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "public-model-team-admin@example.com",
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
                "email": "public-model-team-admin@example.com",
                "password": "team-admin-password",
            },
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        widened_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "access",
                "scope_type": "team",
                "team_id": str(team.id),
                "access_policy": {
                    "name": "Team public model child",
                    "public_models": [
                        {
                                "public_model_name": "chat-large",
                            "routing_mode": "ordered_fallback",
                            "fallback_on": ["provider_5xx"],
                            "candidates": [
                                {
                                    "provider_id": str(provider.id),
                                    "credential_pool_id": str(pool.id),
                                    "model_offering_id": str(model.id),
                                }
                            ],
                        }
                    ],
                },
            },
        )

    assert parent_policy.status_code == 201
    assert widened_response.status_code == 400


@pytest.mark.asyncio
async def test_scoped_access_policy_can_create_narrowed_public_model(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    team = await _create_team_fixture(db_session, name="Scoped Narrow Public Model Team")
    provider, pool, model = await _create_provider_fixture(
        db_session, name="scoped-narrow-public-model"
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
                "name": "Org public model parent",
                "public_models": [
                    _public_model_payload(provider.id, pool.id, model.id, name="chat-large")
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "policy_id": parent_policy.json()["policy_id"],
                "scope_type": "org",
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "narrow-public-model-team-admin@example.com",
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
                "email": "narrow-public-model-team-admin@example.com",
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
                    "name": "Team narrowed public model child",
                    "public_models": [
                        {
                                "public_model_name": "chat-large",
                            "routing_mode": "single_route",
                            "candidates": [
                                {
                                    "provider_id": str(provider.id),
                                    "credential_pool_id": str(pool.id),
                                    "model_offering_id": str(model.id),
                                }
                            ],
                        }
                    ],
                },
            },
        )

    assert parent_policy.status_code == 201
    assert narrowed_response.status_code == 201
    public_models = narrowed_response.json()["access_policy"]["public_models"]
    assert public_models[0]["public_model_name"] == "chat-large"
    assert public_models[0]["routing_mode"] == "single_route"


@pytest.mark.asyncio
async def test_scoped_access_policy_cannot_add_parent_public_model_fallback_reason(
    app_client,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "default_admin_email", "admin@example.com")
    monkeypatch.setattr(bootstrap.settings, "default_admin_password", "correct-password")
    await bootstrap.sync_default_workspace(db_session)
    team = await _create_team_fixture(db_session, name="Scoped Fallback Reason Team")
    provider, pool, model = await _create_provider_fixture(
        db_session, name="scoped-fallback-reason"
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
                "name": "Org ordered parent",
                "public_models": [
                    {
                        "public_model_name": "chat-parent",
                        "routing_mode": "ordered_fallback",
                        "fallback_on": ["provider_5xx"],
                        "candidates": [
                            {
                                "provider_id": str(provider.id),
                                "credential_pool_id": str(pool.id),
                                "model_offering_id": str(model.id),
                            }
                        ],
                    }
                ],
            },
        )
        await client.post(
            "/api/v1/policies/assignments",
            headers=admin_headers,
            json={
                "policy_type": "access",
                "policy_id": parent_policy.json()["policy_id"],
                "scope_type": "org",
            },
        )
        member_response = await client.post(
            "/api/v1/auth/members",
            headers=admin_headers,
            json={
                "email": "fallback-reason-team-admin@example.com",
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
                "email": "fallback-reason-team-admin@example.com",
                "password": "team-admin-password",
            },
        )
        scoped_headers = {"Authorization": f"Bearer {scoped_login.json()['access_token']}"}
        widened_response = await client.post(
            "/api/v1/policies/assignments/scoped-policy",
            headers=scoped_headers,
            json={
                "policy_type": "access",
                "scope_type": "team",
                "team_id": str(team.id),
                "access_policy": {
                    "name": "Team widened fallback reason",
                    "public_models": [
                        {
                            "public_model_name": "chat-parent",
                            "routing_mode": "ordered_fallback",
                            "fallback_on": ["provider_5xx", "rate_limited"],
                            "candidates": [
                                {
                                    "provider_id": str(provider.id),
                                    "credential_pool_id": str(pool.id),
                                    "model_offering_id": str(model.id),
                                }
                            ],
                        }
                    ],
                },
            },
        )

    assert parent_policy.status_code == 201
    assert widened_response.status_code == 400

