from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.report_utils import (
    aggregate_cost_cents_expression,
    aggregate_micro_cents_to_cents,
)


class UsageCostSummary(BaseModel):
    request_count: int = 0
    cost_cents: int = 0


async def get_recent_provider_usage_summary(
    *,
    org_id: UUID,
    provider_id: UUID,
    since: datetime,
    db: AsyncSession,
) -> UsageCostSummary:
    return await _usage_summary(
        org_id=org_id,
        since=since,
        db=db,
        filters=[UsageRecord.provider_id == provider_id],
    )


async def get_recent_provider_credential_usage_summary(
    *,
    org_id: UUID,
    provider_credential_id: UUID,
    since: datetime,
    db: AsyncSession,
) -> UsageCostSummary:
    return await _usage_summary(
        org_id=org_id,
        since=since,
        db=db,
        filters=[UsageRecord.provider_credential_id == provider_credential_id],
    )


async def get_recent_provider_model_usage_summary(
    *,
    org_id: UUID,
    provider_id: UUID,
    provider_model: str,
    since: datetime,
    db: AsyncSession,
) -> UsageCostSummary:
    return await _usage_summary(
        org_id=org_id,
        since=since,
        db=db,
        filters=[
            UsageRecord.provider_id == provider_id,
            UsageRecord.provider_model == provider_model,
        ],
    )


async def get_recent_workspace_usage_summary(
    *,
    org_id: UUID,
    since: datetime,
    db: AsyncSession,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
) -> UsageCostSummary:
    filters = []
    if team_id is not None:
        filters.append(UsageRecord.team_id == team_id)
    if project_id is not None:
        filters.append(UsageRecord.project_id == project_id)
    if virtual_key_id is not None:
        filters.append(UsageRecord.virtual_key_id == virtual_key_id)
    return await _usage_summary(org_id=org_id, since=since, db=db, filters=filters)


async def _usage_summary(
    *,
    org_id: UUID,
    since: datetime,
    db: AsyncSession,
    filters: list,
) -> UsageCostSummary:
    row = (
        await db.execute(
            select(
                func.count(UsageRecord.id),
                aggregate_cost_cents_expression(),
            ).where(
                UsageRecord.org_id == org_id,
                UsageRecord.created_at >= since,
                *filters,
            )
        )
    ).one()
    return UsageCostSummary(
        request_count=int(row[0]),
        cost_cents=aggregate_micro_cents_to_cents(row[1]),
    )
