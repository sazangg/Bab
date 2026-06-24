from typing import Protocol
from uuid import UUID

from app.modules.usage.accounting import UsageAccounting
from app.modules.usage.costing.base import CostingContext
from app.modules.usage.costing.registry import default_cost_calculator_registry


class CostResolvedAccess(Protocol):
    provider_id: UUID
    provider_model: str
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None


def calculate_cost_cents(*, resolved: CostResolvedAccess, usage: UsageAccounting) -> int | None:
    return default_cost_calculator_registry.calculate_cents(
        context=_costing_context(resolved),
        usage=usage,
    )


def calculate_cost_micro_cents(
    *,
    resolved: CostResolvedAccess,
    usage: UsageAccounting,
) -> int | None:
    return default_cost_calculator_registry.calculate_micro_cents(
        context=_costing_context(resolved),
        usage=usage,
    )


def _costing_context(resolved: CostResolvedAccess) -> CostingContext:
    return CostingContext(
        provider_id=str(resolved.provider_id),
        provider_model=resolved.provider_model,
        input_price_per_million_tokens=resolved.input_price_per_million_tokens,
        output_price_per_million_tokens=resolved.output_price_per_million_tokens,
    )

