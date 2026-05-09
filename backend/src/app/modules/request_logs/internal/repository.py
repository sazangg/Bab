from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.request_logs.internal.models import RequestLog
from app.modules.request_logs.schemas import RecordRequestLog


async def create_request_log(*, payload: RecordRequestLog, db: AsyncSession) -> RequestLog:
    request_log = RequestLog(**payload.model_dump())
    db.add(request_log)
    await db.flush()
    return request_log


async def list_request_logs(
    *,
    org_id: UUID,
    limit: int,
    db: AsyncSession,
) -> list[RequestLog]:
    result = await db.scalars(
        select(RequestLog)
        .where(RequestLog.org_id == org_id)
        .order_by(RequestLog.created_at.desc())
        .limit(limit)
    )
    return list(result)
