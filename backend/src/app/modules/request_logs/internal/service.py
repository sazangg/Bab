from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope, transaction
from app.modules.request_logs.internal import repository
from app.modules.request_logs.internal.models import RequestLog
from app.modules.request_logs.schemas import RecordRequestLog, RequestLogResponse


async def record_request_log(*, payload: RecordRequestLog, db: AsyncSession) -> None:
    async with transaction(db):
        await repository.create_request_log(payload=payload, db=db)


async def list_request_logs(
    *,
    scope: Scope,
    limit: int,
    db: AsyncSession,
) -> list[RequestLogResponse]:
    request_logs = await repository.list_request_logs(org_id=scope.org_id, limit=limit, db=db)
    return [_to_response(request_log) for request_log in request_logs]


def _to_response(request_log: RequestLog) -> RequestLogResponse:
    return RequestLogResponse.model_validate(request_log)
