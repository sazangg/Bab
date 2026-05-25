from datetime import UTC, datetime
from types import SimpleNamespace

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
