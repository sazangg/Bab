from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.costing.base import CostingContext
from app.modules.usage.costing.registry import CostCalculatorRegistry
from app.modules.usage.costing.token_pricing import TokenPricingCostCalculator


def test_token_pricing_calculator_returns_none_without_prices() -> None:
    registry = CostCalculatorRegistry(calculators=[TokenPricingCostCalculator()])

    cost = registry.calculate_cents(
        context=CostingContext(
            provider_id="provider",
            provider_model="model",
            input_price_per_million_tokens=None,
            output_price_per_million_tokens=None,
        ),
        usage=UsageAccounting(
            prompt_tokens=1000,
            completion_tokens=1000,
            total_tokens=2000,
            usage_source="provider",
        ),
    )

    assert cost is None


def test_token_pricing_calculator_rounds_up_to_cents() -> None:
    registry = CostCalculatorRegistry(calculators=[TokenPricingCostCalculator()])

    cost = registry.calculate_cents(
        context=CostingContext(
            provider_id="provider",
            provider_model="model",
            input_price_per_million_tokens=10,
            output_price_per_million_tokens=30,
        ),
        usage=UsageAccounting(
            prompt_tokens=1000,
            completion_tokens=1000,
            total_tokens=2000,
            usage_source="provider",
        ),
    )

    assert cost == 1
