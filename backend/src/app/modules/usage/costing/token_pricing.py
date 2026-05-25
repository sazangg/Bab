import math

from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.costing.base import CostingContext


class TokenPricingCostCalculator:
    name = "token_pricing"

    def supports(self, context: CostingContext) -> bool:
        return (
            context.input_price_per_million_tokens is not None
            or context.output_price_per_million_tokens is not None
        )

    def calculate_cents(self, *, context: CostingContext, usage: UsageAccounting) -> int | None:
        if usage.prompt_tokens is None and usage.completion_tokens is None:
            return None
        if not self.supports(context):
            return None
        input_cost = (usage.prompt_tokens or 0) * (context.input_price_per_million_tokens or 0)
        output_cost = (usage.completion_tokens or 0) * (
            context.output_price_per_million_tokens or 0
        )
        total_cost = input_cost + output_cost
        if total_cost <= 0:
            return 0
        return math.ceil(total_cost / 1_000_000)
