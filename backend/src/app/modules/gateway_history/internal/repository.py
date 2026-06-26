from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.request_ids import current_request_id
from app.modules.gateway_history.internal.models import (
    GatewayPolicyDecision,
    GatewayRequest,
    GatewayRouteAttempt,
)
from app.modules.gateway_history.schemas import (
    CreateGatewayRequest,
    FinalizeGatewayRequest,
    GatewayRequestResolvedSubject,
)


async def create_gateway_request(
    *,
    payload: CreateGatewayRequest,
    db: AsyncSession,
) -> GatewayRequest:
    data = payload.model_dump()
    data["request_id"] = data["request_id"] or current_request_id()
    started_at = data.get("started_at") or datetime.now(UTC)
    data["started_at"] = started_at
    data["trace_expires_at"] = started_at + timedelta(days=settings.trace_retention_days)
    gateway_request = GatewayRequest(**data)
    db.add(gateway_request)
    await db.flush()
    return gateway_request


async def finalize_gateway_request(
    *,
    gateway_request_id: UUID,
    payload: FinalizeGatewayRequest,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRequest)
        .where(GatewayRequest.id == gateway_request_id)
        .values(**payload.model_dump(), completed_at=datetime.now(UTC))
    )


async def attach_gateway_request_subject(
    *,
    gateway_request_id: UUID,
    subject: GatewayRequestResolvedSubject,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRequest)
        .where(GatewayRequest.id == gateway_request_id)
        .values(
            org_id=subject.org_id,
            team_id=subject.team_id,
            project_id=subject.project_id,
            virtual_key_id=subject.virtual_key_id,
        )
    )


async def attach_gateway_request_resolution(
    *,
    gateway_request_id: UUID,
    values: dict,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRequest)
        .where(GatewayRequest.id == gateway_request_id)
        .values(**values)
    )


async def create_gateway_route_attempt(
    *,
    values: dict,
    db: AsyncSession,
) -> GatewayRouteAttempt:
    attempt = GatewayRouteAttempt(**values)
    db.add(attempt)
    await db.flush()
    return attempt


async def update_gateway_route_attempt(
    *,
    route_attempt_id: UUID,
    values: dict,
    db: AsyncSession,
) -> None:
    await db.execute(
        update(GatewayRouteAttempt)
        .where(GatewayRouteAttempt.id == route_attempt_id)
        .values(**values)
    )


async def create_gateway_policy_decision(
    *,
    values: dict,
    db: AsyncSession,
) -> GatewayPolicyDecision:
    decision = GatewayPolicyDecision(**values)
    db.add(decision)
    await db.flush()
    return decision


async def get_gateway_request(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> GatewayRequest | None:
    return await db.scalar(
        select(GatewayRequest).where(
            GatewayRequest.id == gateway_request_id,
            GatewayRequest.org_id == org_id,
        )
    )


async def list_gateway_requests(
    *,
    org_id: UUID,
    since: datetime | None,
    until: datetime | None,
    team_id: UUID | None,
    project_id: UUID | None,
    virtual_key_id: UUID | None,
    provider_id: UUID | None,
    public_model_name: str | None,
    requested_model: str | None,
    request_id: str | None,
    status: str | None,
    fallback: str | None,
    error_code: str | None,
    search: str | None,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
    limit: int,
    offset: int,
    now: datetime,
    db: AsyncSession,
) -> list[GatewayRequest]:
    filters = [
        GatewayRequest.org_id == org_id,
        GatewayRequest.trace_expires_at > now,
    ]
    if since is not None:
        filters.append(GatewayRequest.started_at >= since)
    if until is not None:
        filters.append(GatewayRequest.started_at <= until)
    if team_id is not None:
        filters.append(GatewayRequest.team_id == team_id)
    if project_id is not None:
        filters.append(GatewayRequest.project_id == project_id)
    if virtual_key_id is not None:
        filters.append(GatewayRequest.virtual_key_id == virtual_key_id)
    if provider_id is not None:
        route_attempt_exists = (
            select(1)
            .select_from(GatewayRouteAttempt)
            .where(
                GatewayRouteAttempt.gateway_request_id == GatewayRequest.id,
                GatewayRouteAttempt.provider_id == provider_id,
            )
            .exists()
        )
        filters.append(
            or_(
                GatewayRequest.final_provider_id == provider_id,
                route_attempt_exists,
            )
        )
    if public_model_name:
        filters.append(GatewayRequest.public_model_name == public_model_name.strip())
    if requested_model:
        filters.append(GatewayRequest.requested_model == requested_model.strip())
    if request_id:
        filters.append(GatewayRequest.request_id == request_id.strip())
    if fallback == "attempted":
        filters.append(GatewayRequest.fallback_attempted.is_(True))
    elif fallback == "not_attempted":
        filters.append(GatewayRequest.fallback_attempted.is_(False))
    if error_code:
        filters.append(GatewayRequest.final_error_code == error_code.strip())
    if search:
        term = search.strip()
        filters.append(
            or_(
                GatewayRequest.request_id.icontains(term, autoescape=True),
                GatewayRequest.requested_model.icontains(term, autoescape=True),
                GatewayRequest.public_model_name.icontains(term, autoescape=True),
                GatewayRequest.final_provider_model.icontains(term, autoescape=True),
                GatewayRequest.final_error_code.icontains(term, autoescape=True),
            )
        )
    if status:
        filters.append(_gateway_request_status_filter(status))
    _add_allowed_gateway_request_scope_filters(
        filters,
        allowed_team_ids=allowed_team_ids,
        allowed_project_ids=allowed_project_ids,
        allowed_virtual_key_ids=allowed_virtual_key_ids,
    )
    result = await db.scalars(
        select(GatewayRequest)
        .where(*filters)
        .order_by(GatewayRequest.started_at.desc(), GatewayRequest.id.desc())
        .limit(limit + 1)
        .offset(offset)
    )
    return list(result)


async def list_gateway_route_attempts(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> list[GatewayRouteAttempt]:
    result = await db.scalars(
        select(GatewayRouteAttempt)
        .where(
            GatewayRouteAttempt.gateway_request_id == gateway_request_id,
            GatewayRouteAttempt.org_id == org_id,
        )
        .order_by(GatewayRouteAttempt.attempt_index, GatewayRouteAttempt.started_at)
    )
    return list(result)


async def list_gateway_policy_decisions(
    *,
    gateway_request_id: UUID,
    org_id: UUID,
    db: AsyncSession,
) -> list[GatewayPolicyDecision]:
    result = await db.scalars(
        select(GatewayPolicyDecision)
        .where(
            GatewayPolicyDecision.gateway_request_id == gateway_request_id,
            GatewayPolicyDecision.org_id == org_id,
        )
        .order_by(GatewayPolicyDecision.created_at)
    )
    return list(result)


def _add_allowed_gateway_request_scope_filters(
    filters: list,
    *,
    allowed_team_ids: set[UUID] | None,
    allowed_project_ids: set[UUID] | None,
    allowed_virtual_key_ids: set[UUID] | None,
) -> None:
    if (
        allowed_team_ids is None
        and allowed_project_ids is None
        and allowed_virtual_key_ids is None
    ):
        return
    scope_filters = []
    if allowed_team_ids:
        scope_filters.append(GatewayRequest.team_id.in_(allowed_team_ids))
    if allowed_project_ids:
        scope_filters.append(GatewayRequest.project_id.in_(allowed_project_ids))
    if allowed_virtual_key_ids:
        scope_filters.append(GatewayRequest.virtual_key_id.in_(allowed_virtual_key_ids))
    filters.append(or_(*scope_filters) if scope_filters else GatewayRequest.id.is_(None))


def _gateway_request_status_filter(status: str):
    denied_codes = {
        "invalid_virtual_key",
        "access_denied",
        "guardrail_denied",
        "guardrail_output_denied",
        "limit_exceeded",
        "request_validation_denied",
        "request_body_too_large",
    }
    denied_statuses = {400, 401, 403, 404, 413, 422, 429}
    if status == "pending":
        return GatewayRequest.completed_at.is_(None)
    if status == "succeeded":
        return (
            GatewayRequest.final_http_status.is_not(None)
            & (GatewayRequest.final_http_status >= 200)
            & (GatewayRequest.final_http_status < 400)
        )
    denied_filter = or_(
        GatewayRequest.final_error_code.in_(denied_codes),
        (
            GatewayRequest.final_http_status.in_(denied_statuses)
            & GatewayRequest.final_error_code.is_not(None)
            & (GatewayRequest.final_error_code != "provider_upstream_error")
            & (GatewayRequest.final_error_code != "provider_unavailable")
        ),
    )
    if status == "denied":
        return denied_filter
    if status == "failed":
        return (
            GatewayRequest.completed_at.is_not(None)
            & (
                (GatewayRequest.final_http_status.is_(None))
                | (GatewayRequest.final_http_status < 200)
                | (GatewayRequest.final_http_status >= 400)
            )
            & ~denied_filter
        )
    return GatewayRequest.id.is_not(None)
