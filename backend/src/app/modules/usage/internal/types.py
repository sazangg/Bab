from typing import Protocol
from uuid import UUID


class LimitBudgetRuleLike(Protocol):
    limit_policy_id: UUID
    limit_policy_name: str
    limit_policy_rule_id: UUID
    rule_name: str
    interval_unit: str
    interval_count: int
    budget_cents: int
