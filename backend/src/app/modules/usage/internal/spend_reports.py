from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.accounting import subtract_months
from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.query_utils import (
    _add_allowed_scope_filters,
    _json_array_contains,
    _usage_filters,
)
from app.modules.usage.internal.report_utils import _breakdown
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
    rows: list[LimitPolicyBudgetBurnRow] = []
    for rule in limit_budget_rule_references:
        rule_since = _limit_rule_window_start(
            interval_unit=rule.interval_unit,
            interval_count=rule.interval_count,
        )
        filters = [
            UsageRecord.org_id == org_id,
            _json_array_contains(UsageRecord.limit_policy_ids, rule.limit_policy_id, db=db),
            _json_array_contains(
                UsageRecord.limit_policy_rule_ids,
                rule.limit_policy_rule_id,
                db=db,
            ),
        ]
        if rule_since is not None:
            filters.append(UsageRecord.created_at >= rule_since)
        window_descriptor = _limit_rule_window_descriptor(
            interval_unit=rule.interval_unit,
            interval_count=rule.interval_count,
        )
        filters.append(
            or_(
                UsageRecord.limit_window_descriptor == window_descriptor,
                UsageRecord.limit_window_descriptor.is_(None),
            )
        )
        if until is not None:
            filters.append(UsageRecord.created_at <= until)
        if team_id is not None:
            filters.append(UsageRecord.team_id == team_id)
        if provider_id is not None:
            filters.append(UsageRecord.provider_id == provider_id)
        if project_id is not None:
            filters.append(UsageRecord.project_id == project_id)
        if virtual_key_id is not None:
            filters.append(UsageRecord.virtual_key_id == virtual_key_id)
        if model:
            filters.append(UsageRecord.provider_model == model)
        _add_allowed_scope_filters(
            filters,
            allowed_team_ids=allowed_team_ids,
            allowed_project_ids=allowed_project_ids,
            allowed_virtual_key_ids=allowed_virtual_key_ids,
        )
        spent_query = select(func.coalesce(func.sum(UsageRecord.cost_cents), 0)).where(*filters)
        spent = (await db.scalar(spent_query)) or 0
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
                spent_cents=int(spent),
                remaining_cents=max(0, rule.budget_cents - int(spent)),
                burn_rate_pct=round((int(spent) / (rule.budget_cents or 1)) * 100, 1),
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

