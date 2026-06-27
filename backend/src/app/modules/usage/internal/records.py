from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_ids import current_request_id
from app.modules.usage.internal.models import UsageRecord
from app.modules.usage.internal.query_utils import _usage_filters
from app.modules.usage.schemas import RecordUsage, UsageRecordResponse


async def create_usage_record(*, payload: RecordUsage, db: AsyncSession) -> UsageRecord:
    data = payload.model_dump()
    data["request_id"] = data["request_id"] or current_request_id()
    usage_record = UsageRecord(**data)
    db.add(usage_record)
    await db.flush()
    return usage_record


async def list_usage_records_for_gateway_request(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    result = await db.scalars(
        select(UsageRecord)
        .where(
            UsageRecord.gateway_request_id == gateway_request_id,
            UsageRecord.org_id == org_id,
        )
        .order_by(UsageRecord.routing_attempt_index, UsageRecord.created_at)
    )
    return [UsageRecordResponse.model_validate(record) for record in result]


async def list_usage_records(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    provider_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    model: str | None,
    request_id: str | None,
    search: str | None,
    matching_provider_credential_ids: set[UUID] | None,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
    limit: int | None,
    offset: int,
    db: AsyncSession,
) -> list[UsageRecordResponse]:
    filters = _usage_filters(
        org_id=org_id,
        since=since,
        until=until,
        team_id=team_id,
        provider_id=provider_id,
        project_id=project_id,
        virtual_key_id=virtual_key_id,
        model=model,
        request_id=request_id,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    if search:
        # autoescape escapes %/_ so a literal wildcard in the term matches verbatim.
        term = search.strip()
        search_filters = [
            UsageRecord.request_id.icontains(term, autoescape=True),
            UsageRecord.requested_model.icontains(term, autoescape=True),
            UsageRecord.provider_model.icontains(term, autoescape=True),
            UsageRecord.error_code.icontains(term, autoescape=True),
        ]
        if matching_provider_credential_ids:
            search_filters.append(
                UsageRecord.provider_credential_id.in_(matching_provider_credential_ids)
            )
        filters.append(
            or_(*search_filters)
        )
    query = select(UsageRecord).where(*filters).order_by(UsageRecord.created_at.desc())
    if limit is not None:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)
    result = await db.scalars(query)
    return [UsageRecordResponse.model_validate(record) for record in result]

