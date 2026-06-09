from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.policies.internal.models import LimitPolicy, LimitPolicyRule
from app.modules.usage import facade as usage_facade
from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.repository import (
    _bucket_datetime,
    _json_array_contains_postgresql,
    _records_to_totals,
)


def test_usage_bucket_datetime_supports_hour_day_and_week() -> None:
    value = datetime(2026, 5, 24, 14, 32, 9, tzinfo=UTC)

    assert _bucket_datetime(value, "hour") == datetime(2026, 5, 24, 14, tzinfo=UTC)
    assert _bucket_datetime(value, "day") == datetime(2026, 5, 24, tzinfo=UTC)
    assert _bucket_datetime(value, "week") == datetime(2026, 5, 18, tzinfo=UTC)


def test_records_to_totals_keeps_known_spend_and_errors() -> None:
    totals = _records_to_totals(
        [
            SimpleNamespace(
                http_status=200,
                latency_ms=100,
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cost_cents=2,
            ),
            SimpleNamespace(
                http_status=429,
                latency_ms=300,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                cost_cents=None,
            ),
        ]
    )

    assert totals.requests == 2
    assert totals.successful_requests == 1
    assert totals.failed_requests == 1
    assert totals.total_tokens == 15
    assert totals.cost_cents == 2
    assert totals.average_latency_ms == 200


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


@pytest.mark.asyncio
async def test_spend_insights_returns_limit_policy_budget_burn(db_session: AsyncSession) -> None:
    org_id = uuid4()
    team_id = uuid4()
    project_id = uuid4()
    limit_policy_id = uuid4()
    limit_policy_rule_id = uuid4()
    db_session.add(
        LimitPolicy(
            id=limit_policy_id,
            org_id=org_id,
            name="Platform budget",
        )
    )
    db_session.add(
        LimitPolicyRule(
            id=limit_policy_rule_id,
            org_id=org_id,
            limit_policy_id=limit_policy_id,
            name="Monthly budget",
            limit_type="budget_cents",
            limit_value=1000,
            interval_unit="month",
            interval_count=1,
        )
    )
    db_session.add(
        UsageRecord(
            org_id=org_id,
            team_id=team_id,
            project_id=project_id,
            limit_policy_ids=[str(limit_policy_id)],
            limit_policy_rule_ids=[str(limit_policy_rule_id)],
            virtual_key_id=uuid4(),
            pool_id=uuid4(),
            provider_id=uuid4(),
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
async def test_usage_summary_splits_confirmed_estimated_and_unknown_spend(
    db_session: AsyncSession,
) -> None:
    org_id = uuid4()
    team_id = uuid4()
    project_id = uuid4()
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": uuid4(),
        "pool_id": uuid4(),
        "provider_id": uuid4(),
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
                total_tokens=15,
                cost_cents=20,
                usage_source="provider_reported",
            ),
            UsageRecord(
                **shared,
                total_tokens=15,
                cost_cents=10,
                usage_source="estimated",
            ),
            UsageRecord(
                **shared,
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


@pytest.mark.asyncio
async def test_limit_policy_usage_matches_exact_json_uuid_values(
    db_session: AsyncSession,
) -> None:
    target_policy_id = uuid4()
    target_rule_id = uuid4()
    target_assignment_id = uuid4()
    overlapping_policy_id = f"prefix-{target_policy_id}-suffix"
    org_id = uuid4()
    team_id = uuid4()
    project_id = uuid4()
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": uuid4(),
        "pool_id": uuid4(),
        "provider_id": uuid4(),
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
    db_session.add_all(
        [
            UsageRecord(
                **shared,
                limit_policy_ids=[str(target_policy_id)],
                limit_policy_rule_ids=[str(target_rule_id)],
                limit_policy_assignment_ids=[str(target_assignment_id)],
                cost_cents=25,
            ),
            UsageRecord(
                **shared,
                limit_policy_ids=[overlapping_policy_id],
                limit_policy_rule_ids=[f"prefix-{target_rule_id}-suffix"],
                limit_policy_assignment_ids=[f"prefix-{target_assignment_id}-suffix"],
                cost_cents=999,
            ),
        ]
    )
    await db_session.commit()

    requests, prompt_tokens, completion_tokens, cost_cents = (
        await usage_facade.summarize_limit_policy_usage(
            limit_policy_id=target_policy_id,
            limit_policy_rule_id=target_rule_id,
            limit_policy_assignment_id=target_assignment_id,
            since=None,
            db=db_session,
        )
    )

    assert requests == 1
    assert prompt_tokens == 10
    assert completion_tokens == 0
    assert cost_cents == 25


@pytest.mark.asyncio
async def test_budget_burn_matches_exact_json_policy_and_rule_ids(
    db_session: AsyncSession,
) -> None:
    org_id = uuid4()
    team_id = uuid4()
    project_id = uuid4()
    policy_id = uuid4()
    rule_id = uuid4()
    db_session.add(LimitPolicy(id=policy_id, org_id=org_id, name="Budget"))
    db_session.add(
        LimitPolicyRule(
            id=rule_id,
            org_id=org_id,
            limit_policy_id=policy_id,
            name="Monthly",
            limit_type="budget_cents",
            limit_value=1000,
            interval_unit="month",
            interval_count=1,
        )
    )
    shared = {
        "org_id": org_id,
        "team_id": team_id,
        "project_id": project_id,
        "virtual_key_id": uuid4(),
        "pool_id": uuid4(),
        "provider_id": uuid4(),
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
    org_id = uuid4()
    team_id = uuid4()
    project_id = uuid4()
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
        "virtual_key_id": uuid4(),
        "pool_id": uuid4(),
        "provider_id": uuid4(),
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
