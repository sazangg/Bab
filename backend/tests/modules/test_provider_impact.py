from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.auth.internal.models import Organization
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    AccessPolicyRouteCandidate,
    LimitPolicy,
    LimitPolicyRule,
)
from app.modules.providers import facade as providers_facade
from app.modules.providers.internal.models import (
    CredentialPool,
    CredentialPoolCredential,
    ModelOffering,
    ProviderCredential,
)
from app.modules.providers.schemas import CreateProviderCredentialRequest, CreateProviderRequest
from app.modules.usage.internal.models import UsageRecord


async def test_provider_impact_detects_policy_routes_and_recent_usage(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Impact Org", slug="impact-org")
    db_session.add(org)
    await db_session.flush()
    actor = AuthenticatedUser(
        id=uuid4(),
        org_id=org.id,
        email="admin@example.com",
        role="super_admin",
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Provider", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    credential = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Primary", api_key="secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    pool = CredentialPool(org_id=org.id, provider_id=provider.id, name="Production")
    model = ModelOffering(
        org_id=org.id,
        provider_id=provider.id,
        provider_model_name="model-a",
        input_modalities=["text"],
        output_modalities=["text"],
    )
    policy = AccessPolicy(org_id=org.id, name="Production access")
    limit_policy = LimitPolicy(org_id=org.id, name="Provider budget")
    db_session.add_all([pool, model, policy, limit_policy])
    await db_session.flush()
    membership = CredentialPoolCredential(
        org_id=org.id,
        pool_id=pool.id,
        provider_credential_id=credential.id,
    )
    public_model = AccessPolicyPublicModel(
        org_id=org.id,
        access_policy_id=policy.id,
        public_model_name="model-a",
        routing_mode="single_route",
        fallback_on=[],
    )
    db_session.add(public_model)
    await db_session.flush()
    candidate = AccessPolicyRouteCandidate(
        org_id=org.id,
        public_model_id=public_model.id,
        provider_id=provider.id,
        credential_pool_id=pool.id,
        model_offering_id=model.id,
    )
    rule = LimitPolicyRule(
        org_id=org.id,
        limit_policy_id=limit_policy.id,
        name="Provider requests",
        limit_type="requests",
        limit_value=100,
        provider_id=provider.id,
    )
    usage = UsageRecord(
        org_id=org.id,
        team_id=uuid4(),
        project_id=uuid4(),
        virtual_key_id=uuid4(),
        pool_id=pool.id,
        provider_id=provider.id,
        requested_model="model-a",
        provider_model="model-a",
        http_status=200,
        latency_ms=10,
        cost_cents=25,
        created_at=datetime.now(UTC),
    )
    usage.provider_credential_id = credential.id
    db_session.add_all([membership, candidate, rule, usage])
    await db_session.commit()

    impact = await providers_facade.get_provider_impact(
        provider_id=provider.id,
        scope=scope,
        db=db_session,
    )

    assert [(item.name, item.route_id) for item in impact.access_policies] == [
        ("Production access", candidate.id)
    ]
    assert impact.active_limit_rule_count == 1
    assert impact.active_pool_count == 1
    assert impact.active_model_count == 1
    assert impact.recent_request_count == 1
    assert impact.recent_cost_cents == 25

    credential_impact = await providers_facade.get_provider_credential_impact(
        provider_id=provider.id,
        provider_credential_id=credential.id,
        scope=scope,
        db=db_session,
    )
    pool_impact = await providers_facade.get_credential_pool_impact(
        provider_id=provider.id,
        pool_id=pool.id,
        scope=scope,
        db=db_session,
    )
    model_impact = await providers_facade.get_model_offering_impact(
        provider_id=provider.id,
        model_offering_id=model.id,
        scope=scope,
        db=db_session,
    )

    assert credential_impact.active_pool_membership_count == 1
    assert credential_impact.recent_request_count == 1
    assert credential_impact.leaves_provider_unroutable is True
    assert [item.route_id for item in pool_impact.access_policies] == [candidate.id]
    assert [item.route_id for item in model_impact.access_policies] == [candidate.id]
    assert model_impact.recent_request_count == 1


async def test_resource_impacts_simulate_actual_routing_chains(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Routing Impact Org", slug=f"routing-impact-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    actor = AuthenticatedUser(
        id=uuid4(), org_id=org.id, email="admin@example.com", role="super_admin"
    )
    scope = Scope(org_id=org.id)
    provider = await providers_facade.create_provider(
        payload=CreateProviderRequest(name="Provider", base_url="https://api.example.test/v1"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    target = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Target", api_key="target-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    outside = await providers_facade.create_provider_credential(
        provider_id=provider.id,
        payload=CreateProviderCredentialRequest(name="Outside", api_key="outside-secret"),
        actor=actor,
        scope=scope,
        db=db_session,
    )
    target_pool = CredentialPool(org_id=org.id, provider_id=provider.id, name="Target pool")
    inactive_pool = CredentialPool(
        org_id=org.id, provider_id=provider.id, name="Inactive pool", is_active=False
    )
    empty_pool = CredentialPool(org_id=org.id, provider_id=provider.id, name="Empty pool")
    model = ModelOffering(
        org_id=org.id,
        provider_id=provider.id,
        provider_model_name="model-a",
        input_modalities=["text"],
        output_modalities=["text"],
    )
    db_session.add_all([target_pool, inactive_pool, empty_pool, model])
    await db_session.flush()
    target_membership = CredentialPoolCredential(
        org_id=org.id,
        pool_id=target_pool.id,
        provider_credential_id=target.id,
    )
    inactive_membership = CredentialPoolCredential(
        org_id=org.id,
        pool_id=inactive_pool.id,
        provider_credential_id=outside.id,
    )
    db_session.add_all([target_membership, inactive_membership])
    await db_session.flush()

    credential_impact = await providers_facade.get_provider_credential_impact(
        provider_id=provider.id,
        provider_credential_id=target.id,
        scope=scope,
        db=db_session,
    )
    pool_impact = await providers_facade.get_credential_pool_impact(
        provider_id=provider.id,
        pool_id=target_pool.id,
        scope=scope,
        db=db_session,
    )
    model_impact = await providers_facade.get_model_offering_impact(
        provider_id=provider.id,
        model_offering_id=model.id,
        scope=scope,
        db=db_session,
    )
    assert credential_impact.leaves_provider_unroutable is True
    assert pool_impact.leaves_provider_unroutable is True
    assert model_impact.leaves_provider_unroutable is True

    alternate_membership = CredentialPoolCredential(
        org_id=org.id,
        pool_id=empty_pool.id,
        provider_credential_id=outside.id,
    )
    alternate_model = ModelOffering(
        org_id=org.id,
        provider_id=provider.id,
        provider_model_name="model-b",
        input_modalities=["text"],
        output_modalities=["text"],
    )
    db_session.add_all([alternate_membership, alternate_model])
    await db_session.flush()

    credential_impact = await providers_facade.get_provider_credential_impact(
        provider_id=provider.id,
        provider_credential_id=target.id,
        scope=scope,
        db=db_session,
    )
    pool_impact = await providers_facade.get_credential_pool_impact(
        provider_id=provider.id,
        pool_id=target_pool.id,
        scope=scope,
        db=db_session,
    )
    model_impact = await providers_facade.get_model_offering_impact(
        provider_id=provider.id,
        model_offering_id=model.id,
        scope=scope,
        db=db_session,
    )
    assert credential_impact.leaves_provider_unroutable is False
    assert pool_impact.leaves_provider_unroutable is False
    assert model_impact.leaves_provider_unroutable is False

    target_row = await db_session.get(ProviderCredential, target.id)
    assert target_row is not None
    target_row.is_active = False
    await db_session.flush()
    inactive_impact = await providers_facade.get_provider_credential_impact(
        provider_id=provider.id,
        provider_credential_id=target.id,
        scope=scope,
        db=db_session,
    )
    assert inactive_impact.leaves_provider_unroutable is False
