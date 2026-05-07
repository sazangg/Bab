from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.internal.models import AuditLog
from app.modules.audit.schemas import RecordAuditEvent


async def create_event(payload: RecordAuditEvent, db: AsyncSession) -> AuditLog:
    event = AuditLog(**payload.model_dump())
    db.add(event)
    await db.flush()
    return event


async def list_events(*, org_id: UUID, db: AsyncSession, limit: int) -> list[AuditLog]:
    result = await db.scalars(
        select(AuditLog)
        .where(AuditLog.org_id == org_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return list(result)
