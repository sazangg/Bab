from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.query_utils import _usage_filters
from app.modules.usage.internal.report_utils import _breakdown
from app.modules.usage.schemas import UsageFilterOptions


async def get_usage_filter_options(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
    db: AsyncSession,
) -> UsageFilterOptions:
    filters = tuple(
        _usage_filters(
            org_id=org_id,
            since=since,
            until=until,
            team_id=team_id,
            provider_id=None,
            project_id=project_id,
            virtual_key_id=None,
            model=None,
            request_id=None,
            allowed_team_ids=allowed_team_ids,
            allowed_project_ids=allowed_project_ids,
            allowed_virtual_key_ids=allowed_virtual_key_ids,
        )
    )
    return UsageFilterOptions(
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
        by_virtual_key=await _breakdown(
            UsageRecord.virtual_key_id,
            None,
            *filters,
            db=db,
        ),
    )

