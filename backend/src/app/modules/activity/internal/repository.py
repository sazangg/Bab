from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.internal.models import ActivityEvent
from app.modules.activity.schemas import RecordActivityEvent


async def create_activity_event(
    *,
    payload: RecordActivityEvent,
    db: AsyncSession,
) -> ActivityEvent:
    data = payload.model_dump()
    data["metadata_"] = data.pop("metadata")
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
    result = await db.scalars(query.order_by(ActivityEvent.created_at.desc()).limit(limit))
    return list(result)
