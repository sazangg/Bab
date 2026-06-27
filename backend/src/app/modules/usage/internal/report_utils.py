from datetime import datetime

from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.schemas import (
    UsageBreakdownRow,
    UsageRecentError,
    UsageSummaryTotals,
)


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
                func.coalesce(func.sum(UsageRecord.cost_cents), 0),
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
    label_column = label_column if label_column is not None else group_column
    query = select(
        group_column,
        label_column,
        func.count(UsageRecord.id),
        func.coalesce(func.sum(case((UsageRecord.http_status < 400, 1), else_=0)), 0),
        func.coalesce(func.sum(case((UsageRecord.http_status >= 400, 1), else_=0)), 0),
        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
        func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0),
        func.coalesce(func.sum(UsageRecord.cost_cents), 0),
        *_spend_classification_columns(),
        func.avg(UsageRecord.latency_ms),
    ).where(*filters)
    query = query.group_by(group_column, label_column).order_by(func.count(UsageRecord.id).desc())
    rows = (await db.execute(query)).all()
    return [_row_to_breakdown(row) for row in rows]


def _row_to_totals(row) -> UsageSummaryTotals:
    return UsageSummaryTotals(
        requests=int(row[0]),
        successful_requests=int(row[1]),
        failed_requests=int(row[2]),
        prompt_tokens=int(row[3]),
        completion_tokens=int(row[4]),
        total_tokens=int(row[5]),
        cost_cents=int(row[6]),
        confirmed_spend_cents=int(row[7]),
        estimated_spend_cents=int(row[8]),
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
        cost_cents=int(row[8]),
        confirmed_spend_cents=int(row[9]),
        estimated_spend_cents=int(row[10]),
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
        (UsageRecord.cost_cents.is_(None))
        | (UsageRecord.usage_source.is_(None))
        | (UsageRecord.usage_source == "unknown")
    )
    return (
        func.coalesce(
            func.sum(
                case(
                    (
                        (UsageRecord.usage_source == "provider_reported")
                        & UsageRecord.cost_cents.is_not(None),
                        UsageRecord.cost_cents,
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
                        & UsageRecord.cost_cents.is_not(None),
                        UsageRecord.cost_cents,
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

