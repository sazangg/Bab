from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.internal import repository
from app.modules.activity.schemas import ActivityEventResponse, RecordActivityEvent
from app.modules.auth.schemas import AuthenticatedUser


async def record_event(*, payload: RecordActivityEvent, db: AsyncSession) -> None:
    await repository.create_activity_event(payload=payload, db=db)


async def record_event_and_commit(*, payload: RecordActivityEvent, db: AsyncSession) -> None:
    await record_event(payload=payload, db=db)
    await db.commit()


async def record_admin_event(
    *,
    actor: AuthenticatedUser,
    category: str,
    action: str,
    message: str,
    db: AsyncSession,
    severity: str = "info",
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    allocation_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    provider_id: UUID | None = None,
    pool_id: UUID | None = None,
    model_offering_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    await record_event(
        payload=RecordActivityEvent(
            org_id=actor.org_id,
            category=category,
            severity=severity,
            action=action,
            message=message,
            actor_user_id=actor.id,
            actor_email=str(actor.email),
            team_id=team_id,
            project_id=project_id,
            allocation_id=allocation_id,
            virtual_key_id=virtual_key_id,
            provider_id=provider_id,
            pool_id=pool_id,
            model_offering_id=model_offering_id,
            metadata=metadata or {},
        ),
        db=db,
    )


async def list_events(
    *,
    org_id: UUID,
    db: AsyncSession,
    category: str | None = None,
    severity: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[ActivityEventResponse]:
    events = await repository.list_activity_events(
        org_id=org_id,
        category=category,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        since=since,
        limit=limit,
        db=db,
    )
    return [
        ActivityEventResponse.model_validate({**event.__dict__, "metadata": event.metadata_})
        for event in events
    ]
