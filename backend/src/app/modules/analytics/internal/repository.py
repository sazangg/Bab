from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.keys.internal.models import VirtualKey
from app.modules.request_logs.internal.models import RequestLog


async def list_request_logs_since(
    *,
    org_id: UUID,
    since: datetime,
    db: AsyncSession,
) -> list[RequestLog]:
    result = await db.scalars(
        select(RequestLog)
        .where(RequestLog.org_id == org_id, RequestLog.created_at >= since)
        .order_by(RequestLog.created_at.desc())
    )
    return list(result.all())


async def list_virtual_keys_by_id(
    *,
    org_id: UUID,
    key_ids: set[UUID],
    db: AsyncSession,
) -> dict[UUID, VirtualKey]:
    if not key_ids:
        return {}

    result = await db.scalars(
        select(VirtualKey).where(
            VirtualKey.org_id == org_id,
            VirtualKey.id.in_(key_ids),
        )
    )
    return {virtual_key.id: virtual_key for virtual_key in result.all()}
