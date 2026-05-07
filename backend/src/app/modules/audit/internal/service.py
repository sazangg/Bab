from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import transaction
from app.modules.audit.internal import repository
from app.modules.audit.schemas import AuditEvent, RecordAuditEvent


async def record_event(payload: RecordAuditEvent, db: AsyncSession) -> AuditEvent:
    async with transaction(db):
        event = await repository.create_event(payload, db)

    return AuditEvent.model_validate(event)


async def list_events(*, org_id: UUID, db: AsyncSession, limit: int) -> list[AuditEvent]:
    limit = max(1, min(limit, 100))
    events = await repository.list_events(org_id=org_id, db=db, limit=limit)
    return [AuditEvent.model_validate(event) for event in events]
