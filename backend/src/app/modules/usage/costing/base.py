from dataclasses import dataclass
from typing import Protocol

from app.modules.usage.accounting import UsageAccounting


@dataclass(frozen=True)
class CostingContext:
    provider_id: str
    provider_model: str
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None
    cached_input_price_per_million_tokens: int | None = None


class CostCalculator(Protocol):
    name: str

    def supports(self, context: CostingContext) -> bool:
        pass

    def calculate_cents(self, *, context: CostingContext, usage: UsageAccounting) -> int | None:
        pass
