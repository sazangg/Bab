from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.query_utils import _usage_filters
from app.modules.usage.internal.report_utils import BreakdownSpec, _breakdowns
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
    breakdowns = await _breakdowns(
        [
            BreakdownSpec(key="provider", group_column=UsageRecord.provider_id),
            BreakdownSpec(
                key="model",
                group_column=UsageRecord.provider_model,
                label_column=UsageRecord.provider_model,
            ),
            BreakdownSpec(key="team", group_column=UsageRecord.team_id),
            BreakdownSpec(key="project", group_column=UsageRecord.project_id),
            BreakdownSpec(key="virtual_key", group_column=UsageRecord.virtual_key_id),
        ],
        *filters,
        db=db,
    )
    return UsageFilterOptions(
        by_provider=breakdowns["provider"],
        by_model=breakdowns["model"],
        by_team=breakdowns["team"],
        by_project=breakdowns["project"],
        by_virtual_key=breakdowns["virtual_key"],
    )

