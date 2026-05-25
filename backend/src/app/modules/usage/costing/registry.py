from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.costing.base import CostCalculator, CostingContext
from app.modules.usage.costing.token_pricing import TokenPricingCostCalculator


class CostCalculatorRegistry:
    def __init__(self, calculators: list[CostCalculator]) -> None:
        self._calculators = calculators

    def calculate_cents(self, *, context: CostingContext, usage: UsageAccounting) -> int | None:
        for calculator in self._calculators:
            if calculator.supports(context):
                return calculator.calculate_cents(context=context, usage=usage)
        return None


default_cost_calculator_registry = CostCalculatorRegistry(
    calculators=[TokenPricingCostCalculator()],
)
