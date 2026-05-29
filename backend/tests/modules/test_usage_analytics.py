from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import Allocation
from app.modules.usage import facade as usage_facade
from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.repository import _bucket_datetime, _records_to_totals


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


@pytest.mark.asyncio
async def test_spend_insights_returns_allocation_budget_burn(db_session: AsyncSession) -> None:
    org_id = uuid4()
    team_id = uuid4()
    project_id = uuid4()
    allocation_id = uuid4()
    db_session.add(
        Allocation(
            id=allocation_id,
            org_id=org_id,
            target_type="team",
            team_id=team_id,
            name="Platform budget",
            budget_cents=1000,
            window="monthly",
        )
    )
    db_session.add(
        UsageRecord(
            org_id=org_id,
            team_id=team_id,
            project_id=project_id,
            allocation_id=allocation_id,
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

    assert insights.allocation_budget_burn[0].allocation_id == allocation_id
    assert insights.allocation_budget_burn[0].spent_cents == 250
    assert insights.allocation_budget_burn[0].remaining_cents == 750
    assert insights.allocation_budget_burn[0].burn_rate_pct == 25
