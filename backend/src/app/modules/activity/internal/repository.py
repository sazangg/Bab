from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.activity.internal.models import ActivityEvent
from app.modules.activity.schemas import RecordActivityEvent


async def create_activity_event(
    *,
    payload: RecordActivityEvent,
    db: AsyncSession,
) -> ActivityEvent:
    data = payload.model_dump()
    data["metadata_"] = data.pop("metadata")
    data["request_id"] = data["request_id"] or current_request_id()
    event = ActivityEvent(**data)
    db.add(event)
    await db.flush()
    return event


async def list_activity_events(
    *,
    org_id: UUID,
    category: str | None,
    severity: str | None,
    entity_type: str | None,
    entity_id: UUID | None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    limit: int,
    since=None,
    db: AsyncSession,
) -> list[ActivityEvent]:
    query = select(ActivityEvent).where(ActivityEvent.org_id == org_id)
    if category is not None:
        query = query.where(ActivityEvent.category == category)
    if severity is not None:
        query = query.where(ActivityEvent.severity == severity)
    if since is not None:
        query = query.where(ActivityEvent.created_at >= since)
    if entity_type is not None and entity_id is not None:
        column = getattr(ActivityEvent, f"{entity_type}_id", None)
        if column is not None:
            query = query.where(column == entity_id)
    if allowed_team_ids is not None or allowed_project_ids is not None:
        scope_filters = []
        if allowed_team_ids:
            scope_filters.append(ActivityEvent.team_id.in_(allowed_team_ids))
        if allowed_project_ids:
            scope_filters.append(ActivityEvent.project_id.in_(allowed_project_ids))
        query = query.where(or_(*scope_filters) if scope_filters else ActivityEvent.id.is_(None))
    result = await db.scalars(query.order_by(ActivityEvent.created_at.desc()).limit(limit))
    return list(result)
