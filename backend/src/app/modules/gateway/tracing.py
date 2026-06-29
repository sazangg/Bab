from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import (
    record_gateway_request_finalized,
    record_gateway_route_attempt_finalized,
)
from app.core.observability import outcome_for_status
from app.core.request_ids import current_request_id
from app.core.tracing import add_span_event, set_span_attributes
from app.modules.gateway_history import facade as gateway_history_facade
from app.modules.gateway_history.schemas import (
    CreateGatewayRequest,
    FinalizeGatewayRequest,
    GatewayRequestResolvedSubject,
)
from app.modules.policy_kernel import repository as policy_kernel_repository
from app.modules.providers.read_models import get_route_attempt_snapshot
from app.modules.usage.accounting import UsageAccounting

logger = structlog.get_logger(__name__)


class GatewayResolvedAccess(Protocol):
    org_id: UUID
    team_id: UUID | None
    project_id: UUID | None
    access_policy_id: UUID | None
    access_policy_revision_id: UUID | None
    access_policy_assignment_id: UUID | None
    access_policy_route_id: UUID | None
    public_model_id: UUID | None
    route_candidate_id: UUID | None
    primary_route_candidate_id: UUID | None
    public_model_name: str | None
    routing_mode: str | None
    model_offering_id: UUID
    virtual_key_id: UUID
    provider_id: UUID
    pool_id: UUID
    provider_key_id: UUID | None
    requested_model: str
    provider_model: str
    input_price_per_million_tokens: int | None
    output_price_per_million_tokens: int | None
    fallback_disabled_reason: str | None


class GatewayResolvedKeySubject(Protocol):
    org_id: UUID
    team_id: UUID
    project_id: UUID
    virtual_key_id: UUID


async def create_gateway_request(
    *,
    resolved: GatewayResolvedAccess | None,
    requested_model: str | None = None,
    gateway_endpoint: str,
    db: AsyncSession,
) -> UUID | None:
    try:
        gateway_request_id = await gateway_history_facade.create_gateway_request(
            payload=CreateGatewayRequest(
                org_id=resolved.org_id if resolved else None,
                team_id=resolved.team_id if resolved else None,
                project_id=resolved.project_id if resolved else None,
                virtual_key_id=resolved.virtual_key_id if resolved else None,
                request_id=current_request_id(),
                gateway_endpoint=gateway_endpoint,
                requested_model=resolved.requested_model if resolved else (requested_model or ""),
                public_model_id=resolved.public_model_id if resolved else None,
                public_model_name=resolved.public_model_name if resolved else None,
                routing_mode=resolved.routing_mode if resolved else None,
            ),
            db=db,
        )
        logger.info(
            "gateway_request_started",
            gateway_request_id=str(gateway_request_id),
            org_id=str(resolved.org_id) if resolved else None,
            team_id=str(resolved.team_id) if resolved and resolved.team_id else None,
            project_id=str(resolved.project_id) if resolved and resolved.project_id else None,
            virtual_key_id=str(resolved.virtual_key_id) if resolved else None,
            requested_model=resolved.requested_model if resolved else requested_model,
            public_model_name=resolved.public_model_name if resolved else None,
            gateway_endpoint=gateway_endpoint,
        )
        set_span_attributes(
            {
                "bab.gateway.endpoint": gateway_endpoint,
                "bab.gateway.request_id": str(gateway_request_id),
            }
        )
        add_span_event(
            "bab.gateway.request",
            {
                "bab.gateway.phase": "started",
                "bab.gateway.endpoint": gateway_endpoint,
                "bab.gateway.request_id": str(gateway_request_id),
            },
        )
        return gateway_request_id
    except Exception:
        await db.rollback()
        return None


async def attach_gateway_request_subject(
    *,
    gateway_request_id: UUID | None,
    key_subject: GatewayResolvedKeySubject,
    db: AsyncSession,
) -> None:
    try:
        await gateway_history_facade.attach_gateway_request_subject(
            gateway_request_id=gateway_request_id,
            subject=GatewayRequestResolvedSubject(
                org_id=key_subject.org_id,
                team_id=key_subject.team_id,
                project_id=key_subject.project_id,
                virtual_key_id=key_subject.virtual_key_id,
            ),
            db=db,
        )
    except Exception:
        logger.exception(
            "gateway_request_subject_attach_failed",
            gateway_request_id=str(gateway_request_id) if gateway_request_id else None,
            org_id=str(key_subject.org_id),
            team_id=str(key_subject.team_id),
            project_id=str(key_subject.project_id),
            virtual_key_id=str(key_subject.virtual_key_id),
        )


async def attach_gateway_request_resolution(
    *,
    gateway_request_id: UUID | None,
    resolved: GatewayResolvedAccess,
    db: AsyncSession,
) -> None:
    try:
        await gateway_history_facade.attach_gateway_request_resolution(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
    except Exception:
        logger.exception(
            "gateway_request_resolution_attach_failed",
            gateway_request_id=str(gateway_request_id) if gateway_request_id else None,
            org_id=str(resolved.org_id),
            team_id=str(resolved.team_id),
            project_id=str(resolved.project_id),
            virtual_key_id=str(resolved.virtual_key_id),
            public_model_id=str(resolved.public_model_id) if resolved.public_model_id else None,
        )


async def finalize_gateway_request(
    *,
    gateway_request_id: UUID | None,
    resolved: GatewayResolvedAccess | None,
    http_status: int,
    attempt_count: int,
    fallback_attempted: bool,
    error_code: str | None,
    db: AsyncSession,
    final_route_attempt_id: UUID | None = None,
    gateway_endpoint: str | None = None,
) -> None:
    if gateway_request_id is None:
        return
    await gateway_history_facade.finalize_gateway_request(
        gateway_request_id=gateway_request_id,
        payload=FinalizeGatewayRequest(
            final_http_status=http_status,
            final_access_policy_id=resolved.access_policy_id if resolved else None,
            final_public_model_id=resolved.public_model_id if resolved else None,
            final_candidate_id=resolved.route_candidate_id if resolved else None,
            final_route_attempt_id=final_route_attempt_id,
            final_provider_id=resolved.provider_id if resolved else None,
            final_credential_pool_id=resolved.pool_id if resolved else None,
            final_model_offering_id=resolved.model_offering_id if resolved else None,
            final_provider_model=resolved.provider_model if resolved else None,
            attempt_count=attempt_count,
            fallback_attempted=fallback_attempted,
            final_error_code=error_code,
        ),
        db=db,
    )
    logger.info(
        "gateway_request_finalized",
        gateway_request_id=str(gateway_request_id),
        org_id=str(resolved.org_id) if resolved else None,
        team_id=str(resolved.team_id) if resolved and resolved.team_id else None,
        project_id=str(resolved.project_id) if resolved and resolved.project_id else None,
        virtual_key_id=str(resolved.virtual_key_id) if resolved else None,
        provider_id=str(resolved.provider_id) if resolved else None,
        credential_pool_id=str(resolved.pool_id) if resolved else None,
        model_offering_id=str(resolved.model_offering_id) if resolved else None,
        requested_model=resolved.requested_model if resolved else None,
        public_model_name=resolved.public_model_name if resolved else None,
        provider_model=resolved.provider_model if resolved else None,
        status_code=http_status,
        outcome=outcome_for_status(http_status),
        error_code=error_code,
        attempt_count=attempt_count,
        fallback_attempted=fallback_attempted,
        route_attempt_id=str(final_route_attempt_id) if final_route_attempt_id else None,
    )
    record_gateway_request_finalized(
        gateway_endpoint=gateway_endpoint,
        status_code=http_status,
        error_code=error_code,
    )
    set_span_attributes(
        {
            "bab.gateway.endpoint": gateway_endpoint,
            "bab.gateway.outcome": outcome_for_status(http_status),
            "bab.gateway.error_code": error_code,
            "bab.gateway.request_id": str(gateway_request_id),
            "bab.gateway.route_attempt_id": str(final_route_attempt_id)
            if final_route_attempt_id
            else None,
        }
    )
    add_span_event(
        "bab.gateway.request",
        {
            "bab.gateway.phase": "finalized",
            "bab.gateway.endpoint": gateway_endpoint,
            "bab.gateway.outcome": outcome_for_status(http_status),
            "bab.gateway.error_code": error_code,
            "bab.gateway.request_id": str(gateway_request_id),
        },
    )


async def record_gateway_route_attempt_started(
    *,
    gateway_request_id: UUID | None,
    resolved: GatewayResolvedAccess,
    attempt_index: int,
    db: AsyncSession,
) -> UUID | None:
    if gateway_request_id is None:
        return None
    snapshot = await _gateway_route_attempt_snapshot(resolved=resolved, db=db)
    route_attempt_id = await gateway_history_facade.create_gateway_route_attempt(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": gateway_request_id,
            "attempt_index": attempt_index,
            "access_policy_id": resolved.access_policy_id,
            "access_policy_revision_id": resolved.access_policy_revision_id,
            "access_public_model_id": resolved.public_model_id,
            "route_candidate_id": resolved.route_candidate_id,
            "primary_route_candidate_id": resolved.primary_route_candidate_id,
            "provider_id": resolved.provider_id,
            "provider_name": snapshot["provider_name"],
            "provider_slug": snapshot["provider_slug"],
            "credential_pool_id": resolved.pool_id,
            "credential_pool_name": snapshot["credential_pool_name"],
            "provider_credential_id": resolved.provider_key_id,
            "provider_credential_name": snapshot["provider_credential_name"],
            "provider_credential_prefix": snapshot["provider_credential_prefix"],
            "provider_model_offering_id": resolved.model_offering_id,
            "provider_model": resolved.provider_model,
            "public_model_name": resolved.public_model_name,
            "status": "started",
            "usage_source": "unknown",
            "pricing_snapshot": {
                "input_price_per_million_tokens": resolved.input_price_per_million_tokens,
                "output_price_per_million_tokens": resolved.output_price_per_million_tokens,
                "provider_model": resolved.provider_model,
            },
            "capability_snapshot": snapshot["capability_snapshot"],
            "route_snapshot": {
                "routing_mode": resolved.routing_mode,
                "fallback_disabled_reason": resolved.fallback_disabled_reason,
                "access_policy_name": snapshot["access_policy_name"],
                "access_policy_assignment_scope_type": snapshot[
                    "access_policy_assignment_scope_type"
                ],
                "public_model_name": resolved.public_model_name,
                "provider_name": snapshot["provider_name"],
                "credential_pool_name": snapshot["credential_pool_name"],
                "provider_credential_name": snapshot["provider_credential_name"],
                "provider_model": resolved.provider_model,
                "provider_model_offering_name": snapshot["provider_model_offering_name"],
            },
            "started_at": datetime.now(UTC),
        },
        db=db,
    )
    assignment = (
        await policy_kernel_repository.get_policy_assignment(
            assignment_id=resolved.access_policy_assignment_id,
            org_id=resolved.org_id,
            db=db,
        )
        if resolved.access_policy_assignment_id is not None
        else None
    )
    await gateway_history_facade.create_gateway_policy_decision(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": gateway_request_id,
            "route_attempt_id": route_attempt_id,
            "decision_type": "provider_routing",
            "stage": "provider_attempt",
            "outcome": "selected",
            "enforced": True,
            "policy_id": resolved.access_policy_id,
            "policy_revision_id": resolved.access_policy_revision_id,
            "assignment_id": resolved.access_policy_assignment_id,
            "assignment_mode": assignment.mode if assignment else None,
            "assignment_scope_type": assignment.scope_type if assignment else None,
            "assignment_team_id": assignment.team_id if assignment else None,
            "assignment_project_id": assignment.project_id if assignment else None,
            "assignment_virtual_key_id": assignment.virtual_key_id if assignment else None,
            "route_candidate_id": resolved.route_candidate_id,
            "reason_code": "route_selected",
            "dimension_snapshot": {
                "public_model_name": resolved.public_model_name,
                "provider_id": str(resolved.provider_id),
                "credential_pool_id": str(resolved.pool_id),
                "provider_model_offering_id": str(resolved.model_offering_id),
            },
            "metadata_": {
                "attempt_index": attempt_index,
                "access_policy_name": snapshot["access_policy_name"],
                "provider_name": snapshot["provider_name"],
                "credential_pool_name": snapshot["credential_pool_name"],
                "provider_model": resolved.provider_model,
            },
        },
        db=db,
    )
    logger.info(
        "gateway_route_attempt_started",
        gateway_request_id=str(gateway_request_id),
        route_attempt_id=str(route_attempt_id),
        org_id=str(resolved.org_id),
        team_id=str(resolved.team_id) if resolved.team_id else None,
        project_id=str(resolved.project_id) if resolved.project_id else None,
        virtual_key_id=str(resolved.virtual_key_id),
        provider_id=str(resolved.provider_id),
        credential_pool_id=str(resolved.pool_id),
        provider_credential_id=str(resolved.provider_key_id) if resolved.provider_key_id else None,
        model_offering_id=str(resolved.model_offering_id),
        requested_model=resolved.requested_model,
        public_model_name=resolved.public_model_name,
        provider_model=resolved.provider_model,
        attempt_index=attempt_index,
    )
    add_span_event(
        "bab.gateway.route_attempt",
        {
            "bab.gateway.phase": "started",
            "bab.gateway.request_id": str(gateway_request_id),
            "bab.gateway.route_attempt_id": str(route_attempt_id),
            "bab.gateway.attempt_index": attempt_index,
        },
    )
    return route_attempt_id


async def finalize_gateway_route_attempt(
    *,
    route_attempt_id: UUID | None,
    status_: str,
    http_status: int | None,
    error_code: str | None,
    failure_reason: str | None,
    latency_ms: int | None,
    usage: UsageAccounting | None,
    cost_cents: int | None,
    cost_micro_cents: int | None,
    usage_source: str = "unknown",
    db: AsyncSession,
) -> None:
    if route_attempt_id is None:
        return
    await gateway_history_facade.update_gateway_route_attempt(
        route_attempt_id=route_attempt_id,
        values={
            "status": status_,
            "http_status": http_status,
            "error_code": error_code,
            "failure_reason": failure_reason,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "cost_cents": cost_cents,
            "cost_micro_cents": cost_micro_cents,
            "usage_source": usage_source,
            "completed_at": datetime.now(UTC),
        },
        db=db,
    )
    logger.info(
        "gateway_route_attempt_finalized",
        route_attempt_id=str(route_attempt_id),
        status=status_,
        status_code=http_status,
        outcome=outcome_for_status(http_status) if http_status is not None else None,
        error_code=error_code,
        failure_reason=failure_reason,
        duration_ms=latency_ms,
    )
    record_gateway_route_attempt_finalized(
        status_code=http_status,
        status=status_,
        error_code=error_code,
        duration_seconds=(latency_ms / 1000) if latency_ms is not None else None,
    )
    add_span_event(
        "bab.gateway.route_attempt",
        {
            "bab.gateway.phase": "finalized",
            "bab.gateway.outcome": outcome_for_status(http_status)
            if http_status is not None
            else None,
            "bab.gateway.error_code": error_code,
            "bab.gateway.route_attempt_id": str(route_attempt_id),
        },
    )


async def record_gateway_access_decision(
    *,
    gateway_request_id: UUID | None,
    resolved: GatewayResolvedAccess,
    db: AsyncSession,
) -> None:
    if gateway_request_id is None:
        return
    assignment = (
        await policy_kernel_repository.get_policy_assignment(
            assignment_id=resolved.access_policy_assignment_id,
            org_id=resolved.org_id,
            db=db,
        )
        if resolved.access_policy_assignment_id is not None
        else None
    )
    await gateway_history_facade.create_gateway_policy_decision(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": gateway_request_id,
            "route_attempt_id": None,
            "decision_type": "access",
            "stage": "access_resolution",
            "outcome": "allowed",
            "effective_action": "allow",
            "enforced": True,
            "policy_id": resolved.access_policy_id,
            "policy_revision_id": resolved.access_policy_revision_id,
            "assignment_id": resolved.access_policy_assignment_id,
            "assignment_mode": assignment.mode if assignment else None,
            "assignment_scope_type": assignment.scope_type if assignment else None,
            "assignment_team_id": assignment.team_id if assignment else None,
            "assignment_project_id": assignment.project_id if assignment else None,
            "assignment_virtual_key_id": assignment.virtual_key_id if assignment else None,
            "rule_id": None,
            "route_candidate_id": resolved.route_candidate_id,
            "reason_code": "access_resolved",
            "message": None,
            "dimension_snapshot": {
                "virtual_key_id": str(resolved.virtual_key_id),
                "requested_model": resolved.requested_model,
                "public_model_id": str(resolved.public_model_id),
                "public_model_name": resolved.public_model_name,
                "routing_mode": resolved.routing_mode,
            },
            "metadata_": {
                "provider_id": str(resolved.provider_id),
                "pool_id": str(resolved.pool_id),
                "provider_model_offering_id": str(resolved.model_offering_id),
                "provider_model": resolved.provider_model,
            },
        },
        db=db,
    )


async def record_gateway_request_validation_decision(
    *,
    gateway_request_id: UUID | None,
    resolved: GatewayResolvedAccess,
    db: AsyncSession,
) -> None:
    if gateway_request_id is None:
        return
    await gateway_history_facade.create_gateway_policy_decision(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": gateway_request_id,
            "route_attempt_id": None,
            "decision_type": "request_validation",
            "stage": "request_body_validation",
            "outcome": "denied",
            "effective_action": "deny",
            "enforced": True,
            "policy_id": None,
            "policy_revision_id": None,
            "assignment_id": None,
            "assignment_mode": None,
            "assignment_scope_type": None,
            "assignment_team_id": None,
            "assignment_project_id": None,
            "assignment_virtual_key_id": None,
            "rule_id": None,
            "route_candidate_id": resolved.route_candidate_id,
            "reason_code": "request_body_too_large",
            "message": "Request body exceeds the configured size limit.",
            "dimension_snapshot": {
                "virtual_key_id": str(resolved.virtual_key_id),
                "requested_model": resolved.requested_model,
                "public_model_id": str(resolved.public_model_id)
                if resolved.public_model_id
                else None,
                "public_model_name": resolved.public_model_name,
                "routing_mode": resolved.routing_mode,
            },
            "metadata_": {
                "provider_id": str(resolved.provider_id),
                "pool_id": str(resolved.pool_id),
                "provider_model_offering_id": str(resolved.model_offering_id),
                "provider_model": resolved.provider_model,
            },
        },
        db=db,
    )


async def _gateway_route_attempt_snapshot(
    *,
    resolved: GatewayResolvedAccess,
    db: AsyncSession,
) -> dict[str, Any]:
    provider_snapshot = await get_route_attempt_snapshot(
        org_id=resolved.org_id,
        provider_id=resolved.provider_id,
        credential_pool_id=resolved.pool_id,
        provider_credential_id=resolved.provider_key_id,
        model_offering_id=resolved.model_offering_id,
        db=db,
    )
    policy = (
        await policy_kernel_repository.get_policy(
            policy_id=resolved.access_policy_id,
            org_id=resolved.org_id,
            db=db,
        )
        if resolved.access_policy_id is not None
        else None
    )
    assignment = (
        await policy_kernel_repository.get_policy_assignment(
            assignment_id=resolved.access_policy_assignment_id,
            org_id=resolved.org_id,
            db=db,
        )
        if resolved.access_policy_assignment_id is not None
        else None
    )
    return {
        "provider_name": provider_snapshot.provider_name,
        "provider_slug": provider_snapshot.provider_slug,
        "credential_pool_name": provider_snapshot.credential_pool_name,
        "provider_credential_name": provider_snapshot.provider_credential_name,
        "provider_credential_prefix": provider_snapshot.provider_credential_prefix,
        "provider_model_offering_name": provider_snapshot.provider_model_offering_name,
        "access_policy_name": policy.name if policy else None,
        "access_policy_assignment_scope_type": assignment.scope_type if assignment else None,
        "capability_snapshot": provider_snapshot.capability_snapshot,
    }

