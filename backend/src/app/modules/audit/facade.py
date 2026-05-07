from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.internal import service
from app.modules.audit.schemas import AuditEvent, RecordAuditEvent


async def record_event(payload: RecordAuditEvent, db: AsyncSession) -> AuditEvent:
    return await service.record_event(payload, db)


async def list_events(
    *,
    org_id: UUID,
    db: AsyncSession,
    limit: int = 50,
) -> list[AuditEvent]:
    return await service.list_events(org_id=org_id, db=db, limit=limit)
