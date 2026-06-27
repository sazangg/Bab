from datetime import datetime
from uuid import UUID

from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.internal.models import UsageRecord


def _usage_filters(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    provider_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    model: str | None,
    request_id: str | None,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
) -> list:
    filters = [UsageRecord.org_id == org_id]
    if since is not None:
        filters.append(UsageRecord.created_at >= since)
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
    if request_id:
        filters.append(UsageRecord.request_id == request_id)
    _add_allowed_scope_filters(
        filters,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    return filters


def _add_allowed_scope_filters(
    filters: list,
    *,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
) -> None:
    if (
        allowed_team_ids is None
        and allowed_project_ids is None
        and allowed_virtual_key_ids is None
    ):
        return
    scope_filters = []
    if allowed_team_ids:
        scope_filters.append(UsageRecord.team_id.in_(allowed_team_ids))
    if allowed_project_ids:
        scope_filters.append(UsageRecord.project_id.in_(allowed_project_ids))
    if allowed_virtual_key_ids:
        scope_filters.append(UsageRecord.virtual_key_id.in_(allowed_virtual_key_ids))
    filters.append(or_(*scope_filters) if scope_filters else UsageRecord.id.is_(None))


def _json_array_contains(column, value: UUID, *, db: AsyncSession):
    value_text = str(value)
    if db.bind and db.bind.dialect.name == "sqlite":
        json_each = func.json_each(column).table_valued("value")
        return select(1).select_from(json_each).where(json_each.c.value == value_text).exists()
    if db.bind and db.bind.dialect.name == "postgresql":
        return _json_array_contains_postgresql(column, value)
    return column.contains([value_text])


def _json_array_contains_postgresql(column, value: UUID):
    return cast(column, JSONB).contains([str(value)])

