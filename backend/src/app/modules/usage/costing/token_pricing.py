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

    def calculate_micro_cents(
        self, *, context: CostingContext, usage: UsageAccounting
    ) -> int | None:
        # Exact cost in micro-cents (1_000_000 == 1 cent): prices are cents-per-million
        # tokens, so tokens * price is already in micro-cents with no rounding. This is
        # the precise value used for budget enforcement; per-request rounding (below) is
        # only for display and would otherwise over-bill sub-cent requests.
        if usage.prompt_tokens is None and usage.completion_tokens is None:
            return None
        if not self.supports(context):
            return None
        input_cost = (usage.prompt_tokens or 0) * (context.input_price_per_million_tokens or 0)
        output_cost = (usage.completion_tokens or 0) * (
            context.output_price_per_million_tokens or 0
        )
        return max(0, input_cost + output_cost)

    def calculate_cents(self, *, context: CostingContext, usage: UsageAccounting) -> int | None:
        micro_cents = self.calculate_micro_cents(context=context, usage=usage)
        if micro_cents is None:
            return None
        return math.ceil(micro_cents / 1_000_000)
