"""Regression tests for cost-precision, negative-token, and calendar-window fixes."""

from datetime import UTC, datetime

from app.modules.usage.accounting import _extract_provider_usage, subtract_months
from app.modules.usage.costing.base import CostingContext
from app.modules.usage.costing.token_pricing import TokenPricingCostCalculator

_CALC = TokenPricingCostCalculator()
# gpt-4o-mini-like pricing: 15 / 60 cents per million tokens.
_CTX = CostingContext(
    provider_id="p",
    provider_model="m",
    input_price_per_million_tokens=15,
    output_price_per_million_tokens=60,
)


def _usage(prompt: int, completion: int):
    from app.modules.usage.accounting import UsageAccounting

    return UsageAccounting(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        usage_source="provider_reported",
    )


# --- #16 exact micro-cent accounting vs rounded display cents ---------------


def test_micro_cents_are_exact_and_display_cents_round_up() -> None:
    usage = _usage(100, 50)  # true cost = (100*15 + 50*60)/1e6 = 0.0045 cents
    assert _CALC.calculate_micro_cents(context=_CTX, usage=usage) == 4500
    # Display still rounds a sub-cent request up to 1 cent...
    assert _CALC.calculate_cents(context=_CTX, usage=usage) == 1
    # ...but the exact value means 222 such requests fit a 1-cent budget
    # (222 * 4500 = 999000 < 1_000_000) rather than tripping after the first.
    assert 222 * 4500 < 1_000_000 <= 223 * 4500


# --- #26 negative provider-reported tokens are clamped ----------------------


def test_negative_provider_tokens_are_clamped_to_zero() -> None:
    usage = _extract_provider_usage(
        {"usage": {"prompt_tokens": -100, "completion_tokens": 5, "total_tokens": -95}}
    )
    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 0


# --- #24 calendar-aligned month subtraction ---------------------------------


def test_subtract_months_is_calendar_aligned() -> None:
    # One month before Mar 31 is Feb 28 (day clamped), not "30 days earlier".
    assert subtract_months(datetime(2026, 3, 31, tzinfo=UTC), 1) == datetime(
        2026, 2, 28, tzinfo=UTC
    )
    # Crossing a year boundary.
    assert subtract_months(datetime(2026, 1, 15, tzinfo=UTC), 2) == datetime(
        2025, 11, 15, tzinfo=UTC
    )
