from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.query_utils import _usage_filters
from app.modules.usage.internal.report_utils import (
    _breakdown,
    _bucket_expression,
    _coerce_report_bucket_value,
    _logical_request_count_expression,
    _recent_errors,
    _row_to_totals,
    _spend_classification_columns,
    _totals,
)
from app.modules.usage.schemas import (
    OrganizationUsageSummary,
    UsageTimeSeriesPoint,
    VirtualKeyUsageSummary,
)


async def get_organization_usage_summary(
    *,
    org_id: UUID,
    window: str,
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
    db: AsyncSession,
) -> OrganizationUsageSummary:
    filters = tuple(
        _usage_filters(
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
    )
    return OrganizationUsageSummary(
        window=window,
        totals=await _totals(*filters, db=db),
        by_provider=await _breakdown(
            UsageRecord.provider_id,
            *filters,
            db=db,
        ),
        by_model=await _breakdown(
            UsageRecord.provider_model,
            UsageRecord.provider_model,
            *filters,
            db=db,
        ),
        by_pool=await _breakdown(
            UsageRecord.pool_id,
            *filters,
            db=db,
        ),
        by_team=await _breakdown(
            UsageRecord.team_id,
            None,
            *filters,
            db=db,
        ),
        by_project=await _breakdown(
            UsageRecord.project_id,
            None,
            *filters,
            db=db,
        ),
        by_access_policy=await _breakdown(
            UsageRecord.access_policy_id,
            *filters,
            UsageRecord.access_policy_id.is_not(None),
            db=db,
        ),
        by_virtual_key=await _breakdown(
            UsageRecord.virtual_key_id,
            None,
            *filters,
            db=db,
        ),
        recent_errors=await _recent_errors(*filters, db=db),
    )


async def get_organization_usage_timeseries(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    grain: str,
    team_id: UUID | None = None,
    provider_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    model: str | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> list[UsageTimeSeriesPoint]:
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
    bucket_expr = _bucket_expression(grain=grain, db=db)
    rows = (
        await db.execute(
            select(
                bucket_expr.label("bucket"),
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
            )
            .where(*filters)
            .group_by(bucket_expr)
            .order_by(bucket_expr.asc())
        )
    ).all()
    return [
        UsageTimeSeriesPoint(
            bucket=_coerce_report_bucket_value(row[0]),
            **_row_to_totals(row[1:]).model_dump(),
        )
        for row in rows
    ]


async def get_virtual_key_usage_summary(
    *,
    virtual_key_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> VirtualKeyUsageSummary:
    base_filters = (UsageRecord.org_id == org_id, UsageRecord.virtual_key_id == virtual_key_id)
    return VirtualKeyUsageSummary(
        virtual_key_id=virtual_key_id,
        totals=await _totals(*base_filters, db=db),
        by_provider=await _breakdown(
            UsageRecord.provider_id,
            *base_filters,
            db=db,
        ),
        by_model=await _breakdown(
            UsageRecord.provider_model,
            UsageRecord.provider_model,
            *base_filters,
            db=db,
        ),
        by_pool=await _breakdown(
            UsageRecord.pool_id,
            *base_filters,
            db=db,
        ),
        by_access_policy=await _breakdown(
            UsageRecord.access_policy_id,
            *base_filters,
            UsageRecord.access_policy_id.is_not(None),
            db=db,
        ),
        recent_errors=await _recent_errors(*base_filters, db=db),
    )

