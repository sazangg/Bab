from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Organization
from app.modules.policies.internal import repository
from app.modules.policies.internal.models import (
    AccessPolicy,
    AccessPolicyPublicModel,
    LimitPolicy,
    LimitPolicyRule,
)
from app.modules.policy_kernel import assignment_scope_target_key
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.policy_kernel.models import PolicyAssignment
from app.modules.providers.internal.models import CredentialPool, ModelOffering, Provider
from app.modules.usage.internal.models import GatewayRequest, GatewayRouteAttempt
from app.modules.workspace.internal.models import Team


async def _create_shared_policy(
    db_session: AsyncSession,
    *,
    org_id,
    kind: str,
    name: str,
):
    return await policy_kernel_repository.create_policy(
        org_id=org_id,
        kind=kind,
        name=name,
        description=None,
        is_active=True,
        db=db_session,
    )


async def _create_revision(db_session: AsyncSession, *, org_id, policy_id, status: str = "active"):
    return await policy_kernel_repository.create_policy_revision(
        org_id=org_id,
        policy_id=policy_id,
        revision_number=1,
        status=status,
        created_by=None,
        db=db_session,
    )


async def test_shared_policy_revision_active_uniqueness(db_session: AsyncSession) -> None:
    org = Organization(name="Shared Policy Org", slug=f"shared-policy-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="access", name="Access policy"
    )
    active = await policy_kernel_repository.create_policy_revision(
        org_id=org.id,
        policy_id=policy.id,
        revision_number=1,
        status="active",
        created_by=None,
        db=db_session,
    )
    await policy_kernel_repository.create_policy_revision(
        org_id=org.id,
        policy_id=policy.id,
        revision_number=2,
        status="draft",
        created_by=None,
        db=db_session,
    )

    assert (
        await policy_kernel_repository.get_active_policy_revision(
            org_id=org.id,
            policy_id=policy.id,
            db=db_session,
        )
    ).id == active.id

    with pytest.raises(IntegrityError):
        await policy_kernel_repository.create_policy_revision(
            org_id=org.id,
            policy_id=policy.id,
            revision_number=3,
            status="active",
            created_by=None,
            db=db_session,
        )


async def test_sqlite_fk_rejects_shared_policy_id_in_legacy_access_policy_fk(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Legacy FK Org", slug=f"legacy-fk-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="access", name="Shared access"
    )
    revision = await _create_revision(db_session, org_id=org.id, policy_id=policy.id)

    db_session.add(
        AccessPolicyPublicModel(
            org_id=org.id,
            access_policy_id=policy.id,
            policy_revision_id=revision.id,
            public_model_name="fast",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_sqlite_fk_rejects_legacy_access_policy_id_in_shared_policy_fk(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Shared FK Org", slug=f"shared-fk-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="access", name="Shared access"
    )
    access_policy = await repository.create_access_policy(
        org_id=org.id,
        policy_id=policy.id,
        name="Legacy access",
        description=None,
        is_active=True,
        db=db_session,
    )
    gateway_request = GatewayRequest(
        org_id=org.id,
        gateway_endpoint="chat_completions",
        requested_model="fast",
        trace_expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(gateway_request)
    await db_session.flush()

    assert access_policy.id != policy.id
    db_session.add(
        GatewayRouteAttempt(
            org_id=org.id,
            gateway_request_id=gateway_request.id,
            attempt_index=0,
            access_policy_id=access_policy.id,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_shared_policy_assignment_open_scope_uniqueness(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Shared Assignment Org", slug=f"shared-assignment-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="access", name="Access policy"
    )
    team = Team(org_id=org.id, name="Assignment Team", slug=f"assignment-team-{uuid4()}")
    db_session.add(team)
    await db_session.flush()
    team_target = assignment_scope_target_key(
        scope_type="team",
        team_id=team.id,
        project_id=None,
        virtual_key_id=None,
    )

    assert team_target == f"team:{team.id}"
    assert (
        assignment_scope_target_key(
            scope_type="org",
            team_id=None,
            project_id=None,
            virtual_key_id=None,
        )
        == "org"
    )
    with pytest.raises(ValueError):
        assignment_scope_target_key(
            scope_type="project",
            team_id=None,
            project_id=None,
            virtual_key_id=None,
        )

    await policy_kernel_repository.create_policy_assignment(
        org_id=org.id,
        values={
            "policy_id": policy.id,
            "policy_type": "access",
            "scope_type": "team",
            "team_id": team.id,
            "scope_target_key": team_target,
            "mode": "enforce",
            "effective_to": datetime(2026, 1, 1, tzinfo=UTC),
            "is_active": True,
        },
        db=db_session,
    )
    await policy_kernel_repository.create_policy_assignment(
        org_id=org.id,
        values={
            "policy_id": policy.id,
            "policy_type": "access",
            "scope_type": "team",
            "team_id": team.id,
            "scope_target_key": team_target,
            "mode": "enforce",
            "is_active": True,
        },
        db=db_session,
    )

    with pytest.raises(IntegrityError):
        await policy_kernel_repository.create_policy_assignment(
            org_id=org.id,
            values={
                "policy_id": policy.id,
                "policy_type": "access",
                "scope_type": "team",
                "team_id": team.id,
                "scope_target_key": team_target,
                "mode": "enforce",
                "is_active": True,
            },
            db=db_session,
        )


async def test_access_policy_requires_shared_policy_link(db_session: AsyncSession) -> None:
    org = Organization(name="Access Link Org", slug=f"access-link-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        AccessPolicy(
            org_id=org.id,
            name="Missing shared policy",
            description=None,
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_limit_policy_requires_shared_policy_link(db_session: AsyncSession) -> None:
    org = Organization(name="Limit Link Org", slug=f"limit-link-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        LimitPolicy(
            org_id=org.id,
            name="Missing shared policy",
            description=None,
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_access_public_model_requires_policy_revision_link(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Public Model Link Org", slug=f"public-model-link-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        AccessPolicyPublicModel(
            org_id=org.id,
            public_model_name="fast",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_limit_rule_requires_policy_revision_link(db_session: AsyncSession) -> None:
    org = Organization(name="Limit Rule Link Org", slug=f"limit-rule-link-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    shared_policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="limit", name="Request limits"
    )
    limit_policy = await repository.create_limit_policy(
        org_id=org.id,
        policy_id=shared_policy.id,
        values={"name": "Request limits", "description": None, "is_active": True},
        db=db_session,
    )
    db_session.add(
        LimitPolicyRule(
            org_id=org.id,
            limit_policy_id=limit_policy.id,
            name="Missing revision",
            limit_type="requests",
            limit_value=100,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_policy_assignment_requires_shared_policy_link(db_session: AsyncSession) -> None:
    org = Organization(name="Assignment Link Org", slug=f"assignment-link-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Assignment Link Team", slug=f"assignment-link-{uuid4()}")
    db_session.add(team)
    await db_session.flush()
    db_session.add(
        PolicyAssignment(
            org_id=org.id,
            policy_type="access",
            scope_type="team",
            team_id=team.id,
            scope_target_key=f"team:{team.id}",
            mode="enforce",
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_access_public_models_can_belong_to_policy_revision(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Access Revision Org", slug=f"access-revision-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="access", name="Access policy"
    )
    revision = await _create_revision(
        db_session, org_id=org.id, policy_id=policy.id, status="draft"
    )

    public_model = await repository.create_access_policy_public_model(
        org_id=org.id,
        access_policy_id=None,
        policy_revision_id=revision.id,
        public_model_name="fast-general",
        routing_mode="ordered_fallback",
        fallback_on=["timeout"],
        max_route_attempts=2,
        is_active=True,
        db=db_session,
    )

    assert public_model.access_policy_id is None
    assert (
        await repository.get_access_policy_revision_public_model_by_name(
            org_id=org.id,
            policy_revision_id=revision.id,
            public_model_name="fast-general",
            db=db_session,
        )
    ).id == public_model.id
    assert [
        item.id
        for item in await repository.list_access_policy_revision_public_models(
            org_id=org.id,
            policy_revision_id=revision.id,
            db=db_session,
        )
    ] == [public_model.id]

    with pytest.raises(IntegrityError):
        await repository.create_access_policy_public_model(
            org_id=org.id,
            access_policy_id=None,
            policy_revision_id=revision.id,
            public_model_name="fast-general",
            routing_mode="single_route",
            fallback_on=[],
            max_route_attempts=None,
            is_active=True,
            db=db_session,
        )


async def test_revision_route_candidates_store_provider_model_offering_id(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Access Route Revision Org", slug=f"access-route-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="access", name="Access policy"
    )
    revision = await _create_revision(
        db_session, org_id=org.id, policy_id=policy.id, status="draft"
    )
    provider = Provider(
        org_id=org.id,
        name="OpenAI",
        slug=f"openai-{uuid4()}",
        base_url="https://api.openai.com/v1",
    )
    db_session.add(provider)
    await db_session.flush()
    pool = CredentialPool(org_id=org.id, provider_id=provider.id, name="Primary")
    offering = ModelOffering(
        org_id=org.id,
        provider_id=provider.id,
        provider_model_name="gpt-4o-mini",
        modality="text",
        is_active=True,
    )
    db_session.add_all([pool, offering])
    await db_session.flush()
    public_model = await repository.create_access_policy_public_model(
        org_id=org.id,
        access_policy_id=None,
        policy_revision_id=revision.id,
        public_model_name="fast-general",
        routing_mode="single_route",
        fallback_on=[],
        max_route_attempts=None,
        is_active=True,
        db=db_session,
    )

    candidate = await repository.create_access_policy_route_candidate(
        org_id=org.id,
        public_model_id=public_model.id,
        provider_id=provider.id,
        credential_pool_id=pool.id,
        model_offering_id=offering.id,
        priority=100,
        weight=100,
        is_active=True,
        db=db_session,
    )

    assert candidate.provider_model_offering_id == offering.id
    assert [
        item.id
        for item in await repository.list_access_policy_revision_route_candidates(
            org_id=org.id,
            policy_revision_id=revision.id,
            db=db_session,
        )
    ] == [candidate.id]


async def test_limit_rule_matchers_and_partitions_are_rule_scoped(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Limit Matcher Org", slug=f"limit-matcher-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    shared_policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="limit", name="Request limits"
    )
    revision = await _create_revision(db_session, org_id=org.id, policy_id=shared_policy.id)
    policy = await repository.create_limit_policy(
        org_id=org.id,
        policy_id=shared_policy.id,
        values={
            "name": "Request limits",
            "description": None,
            "is_active": True,
        },
        db=db_session,
    )
    rule = await repository.create_limit_policy_rule(
        org_id=org.id,
        limit_policy_id=policy.id,
        values={
            "name": "Per public model",
            "limit_type": "requests",
            "limit_value": 100,
            "interval_unit": "day",
            "interval_count": 1,
            "is_active": True,
        },
        policy_revision_id=revision.id,
        db=db_session,
    )

    await repository.create_limit_policy_rule_matcher(
        org_id=org.id,
        rule_id=rule.id,
        dimension="public_model_name",
        operator="eq",
        value_json="fast-general",
        db=db_session,
    )
    await repository.create_limit_policy_rule_matcher(
        org_id=org.id,
        rule_id=rule.id,
        dimension="streaming",
        operator="exists",
        value_json=None,
        db=db_session,
    )
    await repository.create_limit_policy_rule_partition(
        org_id=org.id,
        rule_id=rule.id,
        dimension="project_id",
        position=0,
        db=db_session,
    )
    await repository.create_limit_policy_rule_partition(
        org_id=org.id,
        rule_id=rule.id,
        dimension="public_model_name",
        position=1,
        db=db_session,
    )

    assert [
        (matcher.dimension, matcher.operator, matcher.value_json)
        for matcher in await repository.list_limit_policy_rule_matchers(
            org_id=org.id,
            rule_id=rule.id,
            db=db_session,
        )
    ] == [
        ("public_model_name", "eq", "fast-general"),
        ("streaming", "exists", None),
    ]
    assert [
        (partition.dimension, partition.position)
        for partition in await repository.list_limit_policy_rule_partitions(
            org_id=org.id,
            rule_id=rule.id,
            db=db_session,
        )
    ] == [
        ("project_id", 0),
        ("public_model_name", 1),
    ]

    await repository.delete_limit_policy_rule_matchers(
        org_id=org.id,
        rule_id=rule.id,
        db=db_session,
    )
    await repository.delete_limit_policy_rule_partitions(
        org_id=org.id,
        rule_id=rule.id,
        db=db_session,
    )

    assert (
        await repository.list_limit_policy_rule_matchers(
            org_id=org.id,
            rule_id=rule.id,
            db=db_session,
        )
        == []
    )
    assert (
        await repository.list_limit_policy_rule_partitions(
            org_id=org.id,
            rule_id=rule.id,
            db=db_session,
        )
        == []
    )


async def test_limit_rule_partitions_are_unique_per_rule(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Partition Unique Org", slug=f"partition-unique-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    shared_policy = await _create_shared_policy(
        db_session, org_id=org.id, kind="limit", name="Limits"
    )
    revision = await _create_revision(db_session, org_id=org.id, policy_id=shared_policy.id)
    policy = await repository.create_limit_policy(
        org_id=org.id,
        policy_id=shared_policy.id,
        values={"name": "Limits", "description": None, "is_active": True},
        db=db_session,
    )
    rule = await repository.create_limit_policy_rule(
        org_id=org.id,
        limit_policy_id=policy.id,
        values={
            "name": "Per project",
            "limit_type": "requests",
            "limit_value": 100,
            "interval_unit": "day",
            "interval_count": 1,
            "is_active": True,
        },
        policy_revision_id=revision.id,
        db=db_session,
    )
    await repository.create_limit_policy_rule_partition(
        org_id=org.id,
        rule_id=rule.id,
        dimension="project_id",
        position=0,
        db=db_session,
    )

    with pytest.raises(IntegrityError):
        await repository.create_limit_policy_rule_partition(
            org_id=org.id,
            rule_id=rule.id,
            dimension="public_model_name",
            position=0,
            db=db_session,
        )
