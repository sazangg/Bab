from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.request_logs.internal.models import RequestLog
from app.modules.request_logs.schemas import RecordRequestLog, RequestLogFilters


async def create_request_log(*, payload: RecordRequestLog, db: AsyncSession) -> RequestLog:
    request_log = RequestLog(**payload.model_dump())
    db.add(request_log)
    await db.flush()
    return request_log


async def list_request_logs(
    *,
    org_id: UUID,
    limit: int,
    offset: int,
    filters: RequestLogFilters,
    db: AsyncSession,
) -> list[RequestLog]:
    statement = _apply_filters(select(RequestLog).where(RequestLog.org_id == org_id), filters)
    result = await db.scalars(
        statement.order_by(RequestLog.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


def _apply_filters(
    statement: Select[tuple[RequestLog]], filters: RequestLogFilters
) -> Select[tuple[RequestLog]]:
    if filters.project_id:
        statement = statement.where(RequestLog.project_id == filters.project_id)
    if filters.virtual_key_id:
        statement = statement.where(RequestLog.virtual_key_id == filters.virtual_key_id)
    if filters.provider_id:
        statement = statement.where(RequestLog.provider_id == filters.provider_id)
    if filters.status_code:
        statement = statement.where(RequestLog.http_status == filters.status_code)
    if filters.requested_model:
        statement = statement.where(RequestLog.requested_model == filters.requested_model)
    if filters.provider_model:
        statement = statement.where(RequestLog.provider_model == filters.provider_model)
    return statement
