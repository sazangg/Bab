from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.internal import repository
from app.modules.activity.schemas import ActivityEventResponse, RecordActivityEvent
from app.modules.auth import facade as auth_facade
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
    virtual_key_id: UUID | None = None,
    provider_id: UUID | None = None,
    pool_id: UUID | None = None,
    model_offering_id: UUID | None = None,
    audit_entity_type: str | None = None,
    audit_entity_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    await auth_facade.record_audit_event(
        actor=actor,
        action=action,
        entity_type=(
            audit_entity_type
            or _audit_entity_type(
                team_id=team_id,
                project_id=project_id,
                virtual_key_id=virtual_key_id,
                provider_id=provider_id,
                pool_id=pool_id,
                model_offering_id=model_offering_id,
            )
        ),
        entity_id=(
            audit_entity_id
            if audit_entity_id is not None
            else (
                virtual_key_id
                or project_id
                or team_id
                or provider_id
                or pool_id
                or model_offering_id
            )
        ),
        metadata=metadata or {},
        db=db,
    )
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
            virtual_key_id=virtual_key_id,
            provider_id=provider_id,
            pool_id=pool_id,
            model_offering_id=model_offering_id,
            metadata=metadata or {},
        ),
        db=db,
    )


def _audit_entity_type(
    *,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    provider_id: UUID | None,
    pool_id: UUID | None,
    model_offering_id: UUID | None,
) -> str:
    if virtual_key_id:
        return "virtual_key"
    if project_id:
        return "project"
    if team_id:
        return "team"
    if provider_id:
        return "provider"
    if pool_id:
        return "credential_pool"
    if model_offering_id:
        return "model_offering"
    return "organization"


async def list_events(
    *,
    org_id: UUID,
    db: AsyncSession,
    category: str | None = None,
    severity: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    virtual_key_id: UUID | None = None,
    allowed_team_ids: set[UUID] | None = None,
    allowed_project_ids: set[UUID] | None = None,
    since: datetime | None = None,
    end_at: datetime | None = None,
    search: str | None = None,
    before_at: datetime | None = None,
    before_id: UUID | None = None,
    limit: int | None = 100,
) -> list[ActivityEventResponse]:
    events = await repository.list_activity_events(
        org_id=org_id,
        category=category,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        team_id=team_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        since=since,
        end_at=end_at,
        search=search,
        before_at=before_at,
        before_id=before_id,
        limit=limit,
        db=db,
    )
    return [
        ActivityEventResponse.model_validate({**event.__dict__, "metadata": event.metadata_})
        for event in events
    ]
