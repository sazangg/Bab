from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.request_logs.internal import service
from app.modules.request_logs.schemas import RecordRequestLog, RequestLogFilters, RequestLogResponse


async def record_request_log(*, payload: RecordRequestLog, db: AsyncSession) -> None:
    await service.record_request_log(payload=payload, db=db)


async def list_request_logs(
    *,
    scope: Scope,
    limit: int,
    offset: int,
    filters: RequestLogFilters,
    db: AsyncSession,
) -> list[RequestLogResponse]:
    return await service.list_request_logs(
        scope=scope, limit=limit, offset=offset, filters=filters, db=db
    )
