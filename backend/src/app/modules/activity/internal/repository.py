from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.activity.internal.models import ActivityEvent
from app.modules.activity.metadata import sanitize_metadata
from app.modules.activity.schemas import RecordActivityEvent


async def create_activity_event(
    *,
    payload: RecordActivityEvent,
    db: AsyncSession,
) -> ActivityEvent:
    data = payload.model_dump()
    data["metadata_"] = data.pop("metadata")
    data["metadata_"] = sanitize_metadata(data["metadata_"])
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
    limit: int | None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    allowed_virtual_key_ids: set[UUID] | None = None,
    since: datetime | None = None,
    end_at: datetime | None = None,
    search: str | None = None,
    before_at: datetime | None = None,
    before_id: UUID | None = None,
    db: AsyncSession,
) -> list[ActivityEvent]:
    query = select(ActivityEvent).where(ActivityEvent.org_id == org_id)
    if category is not None:
        query = query.where(ActivityEvent.category == category)
    if severity is not None:
        query = query.where(ActivityEvent.severity == severity)
    if since is not None:
        query = query.where(ActivityEvent.created_at >= since)
    if end_at is not None:
        query = query.where(ActivityEvent.created_at <= end_at)
    if search:
        # autoescape escapes %/_ so a literal wildcard in the term matches verbatim.
        query = query.where(
            or_(
                ActivityEvent.message.icontains(search, autoescape=True),
                ActivityEvent.action.icontains(search, autoescape=True),
                ActivityEvent.actor_email.icontains(search, autoescape=True),
                ActivityEvent.request_id.icontains(search, autoescape=True),
                ActivityEvent.metadata_["reason"].as_string().icontains(search, autoescape=True),
                ActivityEvent.metadata_["requested_model"]
                .as_string()
                .icontains(search, autoescape=True),
                ActivityEvent.metadata_["provider_model"]
                .as_string()
                .icontains(search, autoescape=True),
                ActivityEvent.metadata_["policy_id"].as_string().icontains(search, autoescape=True),
                ActivityEvent.metadata_["rule_id"].as_string().icontains(search, autoescape=True),
            )
        )
    if before_at is not None:
        cursor_filter = ActivityEvent.created_at < before_at
        if before_id is not None:
            cursor_filter = or_(
                cursor_filter,
                and_(ActivityEvent.created_at == before_at, ActivityEvent.id < before_id),
            )
        query = query.where(cursor_filter)
    if entity_type is not None and entity_id is not None:
        column = getattr(ActivityEvent, f"{entity_type}_id", None)
        if column is not None:
            query = query.where(column == entity_id)
    if team_id is not None:
        query = query.where(ActivityEvent.team_id == team_id)
    if project_id is not None:
        query = query.where(ActivityEvent.project_id == project_id)
    if virtual_key_id is not None:
        query = query.where(ActivityEvent.virtual_key_id == virtual_key_id)
    if (
        allowed_team_ids is not None
        or allowed_project_ids is not None
        or allowed_virtual_key_ids is not None
    ):
        scope_filters = []
        if allowed_team_ids:
            scope_filters.append(ActivityEvent.team_id.in_(allowed_team_ids))
        if allowed_project_ids:
            scope_filters.append(ActivityEvent.project_id.in_(allowed_project_ids))
        if allowed_virtual_key_ids:
            scope_filters.append(ActivityEvent.virtual_key_id.in_(allowed_virtual_key_ids))
        query = query.where(or_(*scope_filters) if scope_filters else ActivityEvent.id.is_(None))
    query = query.order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
    if limit is not None:
        query = query.limit(limit)
    result = await db.scalars(query)
    return list(result)
