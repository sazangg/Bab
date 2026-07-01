from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.accounting import subtract_months
from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.query_utils import (
    _add_allowed_scope_filters,
    _json_array_contains,
    _usage_filters,
)
from app.modules.usage.internal.report_utils import (
    _breakdown,
    aggregate_micro_cents_to_cents,
    effective_micro_cents,
)
from app.modules.usage.internal.types import LimitBudgetRuleLike
from app.modules.usage.schemas import LimitPolicyBudgetBurnRow, SpendInsights


async def get_spend_insights(
    *,
    org_id: UUID,
    window: str,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    provider_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    model: str | None,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
    limit_budget_rule_references: list[LimitBudgetRuleLike],
    db: AsyncSession,
) -> SpendInsights:
    filters = _usage_filters(
        org_id=org_id,
        since=since,
        until=until,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=None,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    top_spend_drivers = await _breakdown(
        UsageRecord.provider_model,
        UsageRecord.provider_model,
        *filters,
        db=db,
    )
    return SpendInsights(
        window=window,
        top_spend_drivers=sorted(
            top_spend_drivers,
            key=lambda row: row.cost_cents,
            reverse=True,
        )[:10],
        limit_policy_budget_burn=await _limit_policy_budget_burn(
            org_id=org_id,
            since=since,
            until=until,
            team_id=team_id,
            provider_id=provider_id,
            project_id=project_id,
            virtual_key_id=virtual_key_id,
            model=model,
            allowed_team_ids=allowed_team_ids,
            allowed_project_ids=allowed_project_ids,
            allowed_virtual_key_ids=allowed_virtual_key_ids,
            limit_budget_rule_references=limit_budget_rule_references,
            db=db,
        ),
    )


async def _limit_policy_budget_burn(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
    limit_budget_rule_references: list[LimitBudgetRuleLike],
    db: AsyncSession,
) -> list[LimitPolicyBudgetBurnRow]:
    common_filters = [UsageRecord.org_id == org_id]
    if until is not None:
        common_filters.append(UsageRecord.created_at <= until)
    if team_id is not None:
        common_filters.append(UsageRecord.team_id == team_id)
    if provider_id is not None:
        common_filters.append(UsageRecord.provider_id == provider_id)
    if project_id is not None:
        common_filters.append(UsageRecord.project_id == project_id)
    if virtual_key_id is not None:
        common_filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    if model:
        common_filters.append(UsageRecord.provider_model == model)
    _add_allowed_scope_filters(
        common_filters,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )

    windows_by_interval: dict[tuple[str, int], tuple[datetime | None, str]] = {}
    rules_by_window: dict[tuple[datetime | None, str], list[LimitBudgetRuleLike]] = {}
    for rule in limit_budget_rule_references:
        interval_key = (rule.interval_unit, rule.interval_count)
        window_key = windows_by_interval.setdefault(
            interval_key,
            (
                _limit_rule_window_start(
                    interval_unit=rule.interval_unit,
                    interval_count=rule.interval_count,
                ),
                _limit_rule_window_descriptor(
                    interval_unit=rule.interval_unit,
                    interval_count=rule.interval_count,
                ),
            ),
        )
        rules_by_window.setdefault(window_key, []).append(rule)

    spent_cents_by_rule_id: dict[UUID, int] = {}
    for (rule_since, window_descriptor), rules in rules_by_window.items():
        filters = list(common_filters)
        if rule_since is not None:
            filters.append(UsageRecord.created_at >= rule_since)
        filters.append(
            or_(
                UsageRecord.limit_window_descriptor == window_descriptor,
                UsageRecord.limit_window_descriptor.is_(None),
            )
        )
        columns = [
            func.coalesce(
                func.sum(
                    case(
                        (
                            _json_array_contains(
                                UsageRecord.limit_policy_ids,
                                rule.limit_policy_id,
                                db=db,
                            )
                            & _json_array_contains(
                                UsageRecord.limit_policy_rule_ids,
                                rule.limit_policy_rule_id,
                                db=db,
                            ),
                            effective_micro_cents(
                                UsageRecord.cost_micro_cents,
                                UsageRecord.cost_cents,
                            ),
                        ),
                        else_=0,
                    )
                ),
                0,
            )
            for rule in rules
        ]
        spent_values = (await db.execute(select(*columns).where(*filters))).one()
        for rule, spent in zip(rules, spent_values, strict=True):
            spent_cents_by_rule_id[rule.limit_policy_rule_id] = (
                aggregate_micro_cents_to_cents(int(spent or 0))
            )

    rows: list[LimitPolicyBudgetBurnRow] = []
    for rule in limit_budget_rule_references:
        spent = spent_cents_by_rule_id.get(rule.limit_policy_rule_id, 0)
        rows.append(
            LimitPolicyBudgetBurnRow(
                limit_policy_id=rule.limit_policy_id,
                limit_policy_rule_id=rule.limit_policy_rule_id,
                limit_policy_name=rule.limit_policy_name,
                rule_name=rule.rule_name,
                interval=format_limit_rule_interval(
                    interval_unit=rule.interval_unit,
                    interval_count=rule.interval_count,
                ),
                budget_cents=rule.budget_cents,
                spent_cents=spent,
                remaining_cents=max(0, rule.budget_cents - spent),
                burn_rate_pct=round((spent / (rule.budget_cents or 1)) * 100, 1),
            )
        )
    return sorted(rows, key=lambda row: row.spent_cents, reverse=True)[:20]


def format_limit_rule_interval(*, interval_unit: str, interval_count: int) -> str:
    if interval_unit == "lifetime":
        return "lifetime"
    return f"{interval_count} {interval_unit}{'' if interval_count == 1 else 's'}"


def _limit_rule_window_descriptor(*, interval_unit: str, interval_count: int) -> str:
    if interval_unit == "lifetime":
        return f"{interval_unit}:{interval_count}:lifetime"
    return f"{interval_unit}:{interval_count}:rolling"


def _limit_rule_window_start(*, interval_unit: str, interval_count: int) -> datetime | None:
    now = datetime.now(UTC)
    if interval_unit == "hour":
        return now - timedelta(hours=interval_count)
    if interval_unit == "day":
        return now - timedelta(days=interval_count)
    if interval_unit == "week":
        return now - timedelta(weeks=interval_count)
    if interval_unit == "month":
        return subtract_months(now, interval_count)
    if interval_unit == "year":
        return subtract_months(now, 12 * interval_count)
    return None

