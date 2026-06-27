from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.internal.models import Organization
from app.modules.keys.internal.models import VirtualKey
from app.modules.policies.internal.models import LimitPolicy, LimitPolicyRule
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.policy_kernel.models import PolicyAssignment
from app.modules.providers.internal.models import CredentialPool, Provider
from app.modules.usage import facade as usage_facade
from app.modules.usage.internal.models import LimitPolicyCommittedUsage, UsageRecord
from app.modules.usage.internal.query_utils import _json_array_contains_postgresql
from app.modules.usage.schemas import (
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
)
from app.modules.workspace.internal.models import Project, Team


async def _create_usage_identity(db_session: AsyncSession) -> SimpleNamespace:
    org = Organization(name=f"Usage Org {uuid4()}", slug=f"usage-org-{uuid4()}")
    db_session.add(org)
    await db_session.flush()
    team = Team(org_id=org.id, name="Usage Team", slug=f"usage-team-{uuid4()}")
    db_session.add(team)
    await db_session.flush()
    project = Project(
        org_id=org.id,
        team_id=team.id,
        created_by=uuid4(),
        name="Usage Project",
        slug=f"usage-project-{uuid4()}",
    )
    provider = Provider(
        org_id=org.id,
        name="Usage Provider",
        slug=f"usage-provider-{uuid4()}",
        base_url="https://provider.example.test",
    )
    db_session.add_all([project, provider])
    await db_session.flush()
    pool = CredentialPool(
        org_id=org.id,
        provider_id=provider.id,
        name="Usage Pool",
    )
    virtual_key = VirtualKey(
        org_id=org.id,
        project_id=project.id,
        name="Usage key",
        key_hash=uuid4().hex,
        key_prefix="bab_usage",
    )
    db_session.add_all([pool, virtual_key])
    await db_session.flush()
    return SimpleNamespace(
        org_id=org.id,
        team_id=team.id,
        project_id=project.id,
        virtual_key_id=virtual_key.id,
        provider_id=provider.id,
        pool_id=pool.id,
    )


async def _create_limit_policy_fixture(
    db_session: AsyncSession,
    *,
    org_id,
    policy_id,
    rule_id,
    name: str,
    rule_name: str,
    limit_type: str,
    limit_value: int,
    interval_unit: str = "month",
    interval_count: int = 1,
) -> None:
    shared_policy = await policy_kernel_repository.create_policy(
        org_id=org_id,
        kind="limit",
        name=name,
        description=None,
        is_active=True,
        db=db_session,
    )
    revision = await policy_kernel_repository.create_policy_revision(
        org_id=org_id,
        policy_id=shared_policy.id,
        revision_number=1,
        status="active",
        created_by=None,
        db=db_session,
    )
    db_session.add(
        LimitPolicy(
            id=policy_id,
            policy_id=shared_policy.id,
            org_id=org_id,
            name=name,
        )
    )
    db_session.add(
        LimitPolicyRule(
            id=rule_id,
            org_id=org_id,
            limit_policy_id=policy_id,
            policy_revision_id=revision.id,
            name=rule_name,
            limit_type=limit_type,
            limit_value=limit_value,
            interval_unit=interval_unit,
            interval_count=interval_count,
        )
    )


def test_postgresql_json_array_contains_uses_jsonb_containment_not_like() -> None:
    policy_id = uuid4()
    statement = select(UsageRecord.id).where(
        _json_array_contains_postgresql(UsageRecord.limit_policy_ids, policy_id)
    )

    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),
        )
    )

    assert "@>" in compiled
    assert "::JSONB" in compiled.upper() or "CAST(" in compiled.upper()
    assert "LIKE" not in compiled.upper()


def test_persisted_limit_accounting_payloads_require_policy_references() -> None:
    with pytest.raises(ValidationError):
        RecordLimitPolicyCommittedUsage(
            org_id=uuid4(),
            usage_record_id=uuid4(),
        )

    with pytest.raises(ValidationError):
        RecordLimitPolicyReservation(
            org_id=uuid4(),
            virtual_key_id=uuid4(),
            expires_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_spend_insights_returns_limit_policy_budget_burn(db_session: AsyncSession) -> None:
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    limit_policy_id = uuid4()
    limit_policy_rule_id = uuid4()
    await _create_limit_policy_fixture(
        db_session,
        org_id=org_id,
        policy_id=limit_policy_id,
        rule_id=limit_policy_rule_id,
        name="Platform budget",
        rule_name="Monthly budget",
        limit_type="budget_cents",
        limit_value=1000,
    )
    db_session.add(
        UsageRecord(
            org_id=org_id,
            team_id=team_id,
            project_id=project_id,
            limit_policy_ids=[str(limit_policy_id)],
            limit_policy_rule_ids=[str(limit_policy_rule_id)],
            virtual_key_id=identity.virtual_key_id,
            pool_id=identity.pool_id,
            provider_id=identity.provider_id,
            provider_credential_id=None,
            requested_model="gpt-5-mini",
            provider_model="gpt-5-mini",
            http_status=200,
            latency_ms=100,
            total_tokens=10,
            cost_cents=250,
            usage_source="provider",
        )
    )
    await db_session.commit()

    insights = await usage_facade.get_spend_insights(
        org_id=org_id,
        window="30d",
        db=db_session,
    )

    assert insights.limit_policy_budget_burn[0].limit_policy_id == limit_policy_id
    assert insights.limit_policy_budget_burn[0].limit_policy_rule_id == limit_policy_rule_id
    assert insights.limit_policy_budget_burn[0].spent_cents == 250
    assert insights.limit_policy_budget_burn[0].remaining_cents == 750
    assert insights.limit_policy_budget_burn[0].burn_rate_pct == 25


@pytest.mark.asyncio
async def test_budget_burn_uses_policy_rule_interval_not_usage_window(
    db_session: AsyncSession,
) -> None:
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    limit_policy_id = uuid4()
    limit_policy_rule_id = uuid4()
    await _create_limit_policy_fixture(
        db_session,
        org_id=org_id,
        policy_id=limit_policy_id,
        rule_id=limit_policy_rule_id,
        name="Monthly cap",
        rule_name="Monthly budget",
        limit_type="budget_cents",
        limit_value=1000,
    )
    db_session.add(
        UsageRecord(
            org_id=org_id,
            team_id=team_id,
            project_id=project_id,
            limit_policy_ids=[str(limit_policy_id)],
            limit_policy_rule_ids=[str(limit_policy_rule_id)],
            virtual_key_id=identity.virtual_key_id,
            pool_id=identity.pool_id,
            provider_id=identity.provider_id,
            provider_credential_id=None,
            requested_model="gpt-5-mini",
            provider_model="gpt-5-mini",
            http_status=200,
            latency_ms=100,
            total_tokens=10,
            cost_cents=400,
            usage_source="estimated",
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    await db_session.commit()

    insights = await usage_facade.get_spend_insights(
        org_id=org_id,
        window="24h",
        db=db_session,
    )

    assert insights.limit_policy_budget_burn[0].spent_cents == 400


@pytest.mark.asyncio
async def test_budget_burn_filters_by_limit_window_descriptor(
    db_session: AsyncSession,
) -> None:
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    limit_policy_id = uuid4()
    limit_policy_rule_id = uuid4()
    await _create_limit_policy_fixture(
        db_session,
        org_id=org_id,
        policy_id=limit_policy_id,
        rule_id=limit_policy_rule_id,
        name="Daily cap",
        rule_name="Daily budget",
        limit_type="budget_cents",
        limit_value=1000,
        interval_unit="day",
    )
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "limit_policy_ids": [str(limit_policy_id)],
        "limit_policy_rule_ids": [str(limit_policy_rule_id)],
        "virtual_key_id": identity.virtual_key_id,
        "pool_id": identity.pool_id,
        "provider_id": identity.provider_id,
        "provider_credential_id": None,
        "requested_model": "gpt-5-mini",
        "provider_model": "gpt-5-mini",
        "http_status": 200,
        "latency_ms": 100,
        "total_tokens": 10,
        "usage_source": "estimated",
    }
    db_session.add_all(
        [
            UsageRecord(
                **shared,
                limit_window_descriptor="day:1:rolling",
                cost_cents=250,
            ),
            UsageRecord(
                **shared,
                limit_window_descriptor="month:1:rolling",
                cost_cents=900,
            ),
        ]
    )
    await db_session.commit()

    insights = await usage_facade.get_spend_insights(
        org_id=org_id,
        window="30d",
        db=db_session,
    )

    assert insights.limit_policy_budget_burn[0].spent_cents == 250


@pytest.mark.asyncio
async def test_usage_summary_splits_confirmed_estimated_and_unknown_spend(
    db_session: AsyncSession,
) -> None:
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": identity.virtual_key_id,
        "pool_id": identity.pool_id,
        "provider_id": identity.provider_id,
        "provider_credential_id": None,
        "requested_model": "gpt-5-mini",
        "provider_model": "gpt-5-mini",
        "http_status": 200,
        "latency_ms": 100,
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    db_session.add_all(
        [
            UsageRecord(
                **shared,
                request_id="req-confirmed",
                total_tokens=15,
                cost_cents=20,
                usage_source="provider_reported",
            ),
            UsageRecord(
                **shared,
                request_id="req-estimated",
                total_tokens=15,
                cost_cents=10,
                usage_source="estimated",
            ),
            UsageRecord(
                **shared,
                request_id="req-unknown",
                total_tokens=30,
                cost_cents=None,
                usage_source="unknown",
            ),
        ]
    )
    await db_session.commit()

    summary = await usage_facade.get_organization_usage_summary(
        org_id=org_id,
        window="lifetime",
        db=db_session,
    )
    timeseries = await usage_facade.get_organization_usage_timeseries(
        org_id=org_id,
        window="lifetime",
        grain="day",
        db=db_session,
    )
    records = await usage_facade.list_usage_records(
        org_id=org_id,
        window="lifetime",
        db=db_session,
    )
    matching_records = await usage_facade.list_usage_records(
        org_id=org_id,
        window="lifetime",
        request_id="req-estimated",
        db=db_session,
    )

    assert summary.totals.cost_cents == 30
    assert summary.totals.confirmed_spend_cents == 20
    assert summary.totals.estimated_spend_cents == 10
    assert summary.totals.unknown_usage_count == 1
    assert summary.totals.unknown_total_tokens == 30
    assert summary.by_model[0].confirmed_spend_cents == 20
    assert summary.by_model[0].estimated_spend_cents == 10
    assert summary.by_model[0].unknown_usage_count == 1
    assert timeseries[0].confirmed_spend_cents == 20
    assert timeseries[0].estimated_spend_cents == 10
    assert {record.spend_type for record in records} == {"confirmed", "estimated", "unknown"}
    assert [record.request_id for record in matching_records] == ["req-estimated"]


@pytest.mark.asyncio
async def test_usage_records_support_search_and_offset(db_session: AsyncSession) -> None:
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": identity.virtual_key_id,
        "pool_id": identity.pool_id,
        "provider_id": identity.provider_id,
        "provider_credential_id": None,
        "http_status": 200,
        "latency_ms": 100,
        "total_tokens": 10,
        "cost_cents": 10,
        "usage_source": "estimated",
    }
    db_session.add_all(
        [
            UsageRecord(
                **shared,
                request_id="req-alpha",
                requested_model="gpt-5-mini",
                provider_model="gpt-5-mini",
            ),
            UsageRecord(
                **shared,
                request_id="req-beta",
                requested_model="gpt-5-large",
                provider_model="gpt-5-large",
            ),
            UsageRecord(
                **shared,
                request_id="req-gamma",
                requested_model="claude-sonnet",
                provider_model="claude-sonnet",
            ),
        ]
    )
    await db_session.commit()

    searched = await usage_facade.list_usage_records(
        org_id=org_id,
        window="lifetime",
        search="gpt-5",
        limit=10,
        db=db_session,
    )
    second_page = await usage_facade.list_usage_records(
        org_id=org_id,
        window="lifetime",
        search="gpt-5",
        limit=1,
        offset=1,
        db=db_session,
    )

    assert {record.request_id for record in searched} == {"req-alpha", "req-beta"}
    assert len(second_page) == 1


@pytest.mark.asyncio
async def test_limit_policy_usage_matches_exact_json_uuid_values(
    db_session: AsyncSession,
) -> None:
    target_policy_id = uuid4()
    target_rule_id = uuid4()
    target_assignment_id = uuid4()
    overlapping_policy_id = f"prefix-{target_policy_id}-suffix"
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    shared_policy = await policy_kernel_repository.create_policy(
        org_id=org_id,
        kind="limit",
        name="Exact policy",
        description=None,
        is_active=True,
        db=db_session,
    )
    revision = await policy_kernel_repository.create_policy_revision(
        org_id=org_id,
        policy_id=shared_policy.id,
        revision_number=1,
        status="active",
        created_by=None,
        db=db_session,
    )
    db_session.add(
        LimitPolicy(
            id=target_policy_id,
            policy_id=shared_policy.id,
            org_id=org_id,
            name="Exact policy",
        )
    )
    db_session.add(
        LimitPolicyRule(
            id=target_rule_id,
            org_id=org_id,
            limit_policy_id=target_policy_id,
            policy_revision_id=revision.id,
            name="Exact rule",
            limit_type="requests",
            limit_value=100,
        )
    )
    db_session.add(
        PolicyAssignment(
            id=target_assignment_id,
            org_id=org_id,
            policy_id=shared_policy.id,
            policy_type="limit",
            scope_type="project",
            project_id=project_id,
            scope_target_key=f"project:{project_id}",
            mode="enforce",
        )
    )
    await db_session.flush()
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": identity.virtual_key_id,
        "pool_id": identity.pool_id,
        "provider_id": identity.provider_id,
        "provider_credential_id": None,
        "requested_model": "gpt-5-mini",
        "provider_model": "gpt-5-mini",
        "http_status": 200,
        "latency_ms": 100,
        "prompt_tokens": 10,
        "completion_tokens": 0,
        "total_tokens": 10,
        "usage_source": "estimated",
    }
    target_usage = UsageRecord(
        **shared,
        limit_policy_ids=[str(target_policy_id)],
        limit_policy_rule_ids=[str(target_rule_id)],
        limit_policy_assignment_ids=[str(target_assignment_id)],
        cost_cents=25,
    )
    overlap_usage = UsageRecord(
        **shared,
        limit_policy_ids=[overlapping_policy_id],
        limit_policy_rule_ids=[f"prefix-{target_rule_id}-suffix"],
        limit_policy_assignment_ids=[f"prefix-{target_assignment_id}-suffix"],
        cost_cents=999,
    )
    db_session.add_all([target_usage, overlap_usage])
    await db_session.flush()
    db_session.add(
        LimitPolicyCommittedUsage(
            org_id=org_id,
            usage_record_id=target_usage.id,
            limit_policy_id=target_policy_id,
            limit_policy_revision_id=revision.id,
            limit_policy_rule_id=target_rule_id,
            limit_policy_assignment_id=target_assignment_id,
            counting_unit="logical_request",
            prompt_tokens=10,
            completion_tokens=0,
            total_tokens=10,
            cost_cents=25,
            cost_micro_cents=0,
            dimension_snapshot={},
            created_at=target_usage.created_at,
        )
    )
    await db_session.commit()

    (
        requests,
        prompt_tokens,
        completion_tokens,
        cost_cents,
        cost_micro_cents,
    ) = await usage_facade.summarize_limit_policy_usage(
        limit_policy_id=target_policy_id,
        limit_policy_rule_id=target_rule_id,
        limit_policy_assignment_id=target_assignment_id,
        since=None,
        db=db_session,
    )

    assert requests == 1
    assert prompt_tokens == 10
    assert completion_tokens == 0
    assert cost_cents == 25
    assert cost_micro_cents == 0


@pytest.mark.asyncio
async def test_budget_burn_matches_exact_json_policy_and_rule_ids(
    db_session: AsyncSession,
) -> None:
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    policy_id = uuid4()
    rule_id = uuid4()
    await _create_limit_policy_fixture(
        db_session,
        org_id=org_id,
        policy_id=policy_id,
        rule_id=rule_id,
        name="Budget",
        rule_name="Monthly",
        limit_type="budget_cents",
        limit_value=1000,
    )
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": identity.virtual_key_id,
        "pool_id": identity.pool_id,
        "provider_id": identity.provider_id,
        "provider_credential_id": None,
        "requested_model": "gpt-5-mini",
        "provider_model": "gpt-5-mini",
        "http_status": 200,
        "latency_ms": 100,
        "total_tokens": 10,
        "usage_source": "estimated",
    }
    db_session.add_all(
        [
            UsageRecord(
                **shared,
                limit_policy_ids=[str(policy_id)],
                limit_policy_rule_ids=[str(rule_id)],
                cost_cents=100,
            ),
            UsageRecord(
                **shared,
                limit_policy_ids=[f"prefix-{policy_id}-suffix"],
                limit_policy_rule_ids=[f"prefix-{rule_id}-suffix"],
                cost_cents=900,
            ),
        ]
    )
    await db_session.commit()

    insights = await usage_facade.get_spend_insights(
        org_id=org_id,
        window="lifetime",
        db=db_session,
    )

    assert insights.limit_policy_budget_burn[0].spent_cents == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("grain", "expected_buckets"),
    [
        ("hour", [datetime(2026, 5, 24, 10), datetime(2026, 5, 24, 11)]),
        ("day", [datetime(2026, 5, 24), datetime(2026, 5, 25)]),
        ("week", [datetime(2026, 5, 18), datetime(2026, 5, 25)]),
    ],
)
async def test_usage_timeseries_aggregates_hour_day_and_week_in_sql(
    db_session: AsyncSession,
    grain: str,
    expected_buckets: list[datetime],
) -> None:
    identity = await _create_usage_identity(db_session)
    org_id = identity.org_id
    team_id = identity.team_id
    project_id = identity.project_id
    base = datetime(2026, 5, 24, 10, 15, tzinfo=UTC)
    second_bucket_at = {
        "hour": base.replace(hour=11),
        "day": base + timedelta(days=1),
        "week": base + timedelta(days=1),
    }[grain]
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": identity.virtual_key_id,
        "pool_id": identity.pool_id,
        "provider_id": identity.provider_id,
        "provider_credential_id": None,
        "requested_model": "gpt-5-mini",
        "provider_model": "gpt-5-mini",
        "http_status": 200,
        "latency_ms": 100,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "usage_source": "estimated",
    }
    db_session.add_all(
        [
            UsageRecord(**shared, created_at=base, total_tokens=2, cost_cents=2),
            UsageRecord(**shared, created_at=base.replace(minute=45), total_tokens=3, cost_cents=3),
            UsageRecord(**shared, created_at=second_bucket_at, total_tokens=5, cost_cents=5),
        ]
    )
    await db_session.commit()

    points = await usage_facade.get_organization_usage_timeseries(
        org_id=org_id,
        window="lifetime",
        grain=grain,
        db=db_session,
    )

    assert [point.bucket for point in points] == expected_buckets
    assert [point.total_tokens for point in points] == [5, 5]
