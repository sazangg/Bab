from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.request_logs.internal import service
from app.modules.request_logs.schemas import RecordRequestLog, RequestLogResponse


async def record_request_log(*, payload: RecordRequestLog, db: AsyncSession) -> None:
    await service.record_request_log(payload=payload, db=db)


async def list_request_logs(
    *,
    scope: Scope,
    limit: int,
    db: AsyncSession,
) -> list[RequestLogResponse]:
    return await service.list_request_logs(scope=scope, limit=limit, db=db)
