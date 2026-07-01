from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Integer, String, case, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.schemas import (
    UsageBreakdownRow,
    UsageRecentError,
    UsageSummaryTotals,
)

MICRO_CENTS_PER_CENT = 1_000_000


@dataclass(frozen=True)
class BreakdownSpec:
    key: str
    group_column: ColumnElement
    label_column: ColumnElement | None = None
    extra_filters: tuple[ColumnElement, ...] = field(default_factory=tuple)


def _bucket_expression(*, grain: str, db: AsyncSession):
    dialect_name = db.bind.dialect.name if db.bind else ""
    if dialect_name == "sqlite":
        if grain == "hour":
            return func.strftime("%Y-%m-%d %H:00:00", UsageRecord.created_at)
        if grain == "week":
            weekday_offset = (cast(func.strftime("%w", UsageRecord.created_at), Integer) + 6) % 7
            return func.strftime(
                "%Y-%m-%d 00:00:00",
                func.date(
                    UsageRecord.created_at,
                    func.printf("-%d days", weekday_offset),
                ),
            )
        return func.strftime("%Y-%m-%d 00:00:00", UsageRecord.created_at)
    if grain == "hour":
        return func.date_trunc("hour", UsageRecord.created_at)
    if grain == "week":
        return func.date_trunc("week", UsageRecord.created_at)
    return func.date_trunc("day", UsageRecord.created_at)


def _coerce_report_bucket_value(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def effective_micro_cents(micro_column, cents_column):
    return func.coalesce(micro_column, cents_column * MICRO_CENTS_PER_CENT)


def aggregate_micro_cents_to_cents(value: int | None) -> int:
    if value is None or value <= 0:
        return 0
    return (int(value) + MICRO_CENTS_PER_CENT - 1) // MICRO_CENTS_PER_CENT


def aggregate_cost_cents_expression():
    return func.coalesce(
        func.sum(effective_micro_cents(UsageRecord.cost_micro_cents, UsageRecord.cost_cents)),
        0,
    )


async def _totals(*filters, db: AsyncSession) -> UsageSummaryTotals:
    row = (
        await db.execute(
            select(
                _logical_request_count_expression(),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (UsageRecord.is_final_attempt.is_(True))
                                & (UsageRecord.http_status < 400),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (UsageRecord.is_final_attempt.is_(True))
                                & (UsageRecord.http_status >= 400),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                aggregate_cost_cents_expression(),
                *_spend_classification_columns(),
                func.avg(UsageRecord.latency_ms),
                func.max(UsageRecord.created_at),
            ).where(*filters)
        )
    ).one()
    return _row_to_totals(row)


def _logical_request_count_expression():
    return func.count(func.distinct(func.coalesce(UsageRecord.gateway_request_id, UsageRecord.id)))


async def _breakdown(
    group_column,
    label_column=None,
    *filters,
    db: AsyncSession,
) -> list[UsageBreakdownRow]:
    rows_by_key = await _breakdowns(
        [
            BreakdownSpec(
                key="breakdown",
                group_column=group_column,
                label_column=label_column,
            )
        ],
        *filters,
        db=db,
    )
    return rows_by_key["breakdown"]


async def _breakdowns(
    specs: Sequence[BreakdownSpec],
    *filters,
    db: AsyncSession,
) -> dict[str, list[UsageBreakdownRow]]:
    if not specs:
        return {}
    selects = []
    for spec in specs:
        label_column = spec.label_column if spec.label_column is not None else spec.group_column
        selects.append(
            select(
                literal(spec.key).label("breakdown_key"),
                cast(spec.group_column, String).label("group_value"),
                cast(label_column, String).label("label_value"),
                func.count(UsageRecord.id).label("requests"),
                func.coalesce(
                    func.sum(case((UsageRecord.http_status < 400, 1), else_=0)),
                    0,
                ).label("successful_requests"),
                func.coalesce(
                    func.sum(case((UsageRecord.http_status >= 400, 1), else_=0)),
                    0,
                ).label("failed_requests"),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(
                    func.sum(UsageRecord.completion_tokens),
                    0,
                ).label("completion_tokens"),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0).label("total_tokens"),
                aggregate_cost_cents_expression().label("cost_micro_cents"),
                *_spend_classification_columns(),
                func.avg(UsageRecord.latency_ms).label("average_latency_ms"),
            )
            .where(*filters, *spec.extra_filters)
            .group_by(spec.group_column, label_column)
        )
    rows = (await db.execute(union_all(*selects))).all()
    results = {spec.key: [] for spec in specs}
    for row in rows:
        results[row[0]].append(_row_to_breakdown(row[1:]))
    for breakdown_rows in results.values():
        breakdown_rows.sort(key=lambda item: item.requests, reverse=True)
    return results


def _row_to_totals(row) -> UsageSummaryTotals:
    return UsageSummaryTotals(
        requests=int(row[0]),
        successful_requests=int(row[1]),
        failed_requests=int(row[2]),
        prompt_tokens=int(row[3]),
        completion_tokens=int(row[4]),
        total_tokens=int(row[5]),
        cost_cents=aggregate_micro_cents_to_cents(row[6]),
        confirmed_spend_cents=aggregate_micro_cents_to_cents(row[7]),
        estimated_spend_cents=aggregate_micro_cents_to_cents(row[8]),
        unknown_usage_count=int(row[9]),
        unknown_total_tokens=int(row[10]),
        average_latency_ms=None if row[11] is None else round(row[11]),
        last_request_at=row[12],
    )


def _row_to_breakdown(row) -> UsageBreakdownRow:
    return UsageBreakdownRow(
        id=str(row[0]),
        label=str(row[1]),
        requests=int(row[2]),
        successful_requests=int(row[3]),
        failed_requests=int(row[4]),
        prompt_tokens=int(row[5]),
        completion_tokens=int(row[6]),
        total_tokens=int(row[7]),
        cost_cents=aggregate_micro_cents_to_cents(row[8]),
        confirmed_spend_cents=aggregate_micro_cents_to_cents(row[9]),
        estimated_spend_cents=aggregate_micro_cents_to_cents(row[10]),
        unknown_usage_count=int(row[11]),
        unknown_total_tokens=int(row[12]),
        average_latency_ms=None if row[13] is None else round(row[13]),
        last_request_at=None,
    )


async def _recent_errors(*filters, db: AsyncSession) -> list[UsageRecentError]:
    rows = (
        await db.scalars(
            select(UsageRecord)
            .where(*filters, UsageRecord.http_status >= 400)
            .order_by(UsageRecord.created_at.desc())
            .limit(5)
        )
    ).all()
    return [UsageRecentError.model_validate(record) for record in rows]


def _spend_classification_columns():
    unknown_condition = (
        (UsageRecord.cost_micro_cents.is_(None) & UsageRecord.cost_cents.is_(None))
        | (UsageRecord.usage_source.is_(None))
        | (UsageRecord.usage_source == "unknown")
    )
    return (
        func.coalesce(
            func.sum(
                case(
                    (
                        (UsageRecord.usage_source == "provider_reported")
                        & (
                            UsageRecord.cost_micro_cents.is_not(None)
                            | UsageRecord.cost_cents.is_not(None)
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
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        (UsageRecord.usage_source == "estimated")
                        & (
                            UsageRecord.cost_micro_cents.is_not(None)
                            | UsageRecord.cost_cents.is_not(None)
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
        ),
        func.coalesce(func.sum(case((unknown_condition, 1), else_=0)), 0),
        func.coalesce(
            func.sum(case((unknown_condition, UsageRecord.total_tokens), else_=0)),
            0,
        ),
    )

