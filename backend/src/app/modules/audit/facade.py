from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.audit.actor import AuditActor
from app.modules.audit.internal import service
from app.modules.audit.schemas import AuditEventResponse, AuditVerificationResponse


async def record_audit_event(
    *,
    actor: AuditActor,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict,
    db: AsyncSession,
) -> None:
    await service.record_audit_event(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
        db=db,
    )


async def list_audit_events(
    *,
    scope: Scope,
    db: AsyncSession,
    limit: int | None = 100,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    actor_user_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    search: str | None = None,
    before_at: datetime | None = None,
    before_id: UUID | None = None,
) -> list[AuditEventResponse]:
    return await service.list_audit_events(
        scope=scope,
        db=db,
        limit=limit,
        start_at=start_at,
        end_at=end_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        search=search,
        before_at=before_at,
        before_id=before_id,
    )


async def verify_audit_chain(*, scope: Scope, db: AsyncSession) -> AuditVerificationResponse:
    return await service.verify_audit_chain(scope=scope, db=db)
