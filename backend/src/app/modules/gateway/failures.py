from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import record_gateway_denial
from app.core.tracing import add_span_event
from app.modules.gateway import accounting as gateway_accounting
from app.modules.gateway import guardrails as gateway_guardrails
from app.modules.gateway import limits as gateway_limits
from app.modules.gateway import tracing as gateway_tracing
from app.modules.keys.schemas import ResolvedAccess
from app.modules.providers.errors import ProviderUpstreamError
from app.modules.usage.accounting import unknown_usage


@dataclass(frozen=True)
class GatewayFailureContext:
    resolved: ResolvedAccess | None
    gateway_request_id: UUID | None
    current_route_attempt_id: UUID | None
    final_route_attempt_id: UUID | None
    reservation_ids: list[UUID] = field(default_factory=list)
    attempted_routes: int = 0
    selected_attempt_index: int = 0
    fallback_attempted: bool = False
    started_at: float = 0.0
    gateway_endpoint: str = "chat_completions"

    @property
    def route_attempt_id(self) -> UUID | None:
        return self.final_route_attempt_id or self.current_route_attempt_id

    @property
    def attempt_count(self) -> int:
        return self.attempted_routes or (1 if self.resolved is not None else 0)


async def finalize_invalid_virtual_key(
    *,
    gateway_request_id: UUID | None,
    db: AsyncSession,
) -> None:
    _record_denial(denial_type="invalid_virtual_key", phase="access")
    await gateway_tracing.finalize_gateway_request(
        gateway_request_id=gateway_request_id,
        resolved=None,
        http_status=401,
        attempt_count=0,
        fallback_attempted=False,
        error_code="invalid_virtual_key",
        db=db,
    )


async def finalize_request_body_too_large(
    *,
    context: GatewayFailureContext,
    db: AsyncSession,
) -> None:
    _record_denial(
        denial_type="request_body_too_large",
        gateway_endpoint=context.gateway_endpoint,
        phase="request",
    )
    await gateway_limits.release_reservations(reservation_ids=context.reservation_ids, db=db)
    if context.resolved is not None:
        await gateway_tracing.record_gateway_request_validation_decision(
            gateway_request_id=context.gateway_request_id,
            resolved=context.resolved,
            db=db,
        )
    await _finalize_route_attempt_if_present(
        context=context,
        status_="blocked",
        http_status=413,
        error_code="request_body_too_large",
        db=db,
    )
    await gateway_tracing.finalize_gateway_request(
        gateway_request_id=context.gateway_request_id,
        resolved=context.resolved,
        http_status=413,
        attempt_count=context.attempt_count,
        fallback_attempted=context.fallback_attempted,
        error_code="request_body_too_large",
        db=db,
        final_route_attempt_id=context.route_attempt_id,
        gateway_endpoint=context.gateway_endpoint,
    )


async def finalize_limit_denial(
    *,
    context: GatewayFailureContext,
    denial: gateway_limits.GatewayLimitDeniedError,
    db: AsyncSession,
) -> None:
    _record_denial(
        denial_type="limit_denied",
        gateway_endpoint=context.gateway_endpoint,
        phase="limit",
    )
    await gateway_limits.release_reservations(reservation_ids=context.reservation_ids, db=db)
    if context.resolved is not None:
        await gateway_accounting.record_limit_denial_side_effects(
            resolved=context.resolved,
            denial=denial,
            gateway_request_id=context.gateway_request_id,
            route_attempt_id=context.route_attempt_id,
            db=db,
        )
    await _finalize_route_attempt_if_present(
        context=context,
        status_="blocked",
        http_status=429,
        error_code="limit_exceeded",
        db=db,
    )
    await gateway_tracing.finalize_gateway_request(
        gateway_request_id=context.gateway_request_id,
        resolved=context.resolved,
        http_status=429,
        attempt_count=context.attempt_count,
        fallback_attempted=context.fallback_attempted,
        error_code="limit_exceeded",
        db=db,
        final_route_attempt_id=context.route_attempt_id,
        gateway_endpoint=context.gateway_endpoint,
    )


async def finalize_access_denied(
    *,
    context: GatewayFailureContext,
    message: str,
    record_usage: bool,
    db: AsyncSession,
) -> None:
    _record_denial(
        denial_type="access_denied",
        gateway_endpoint=context.gateway_endpoint,
        phase="access",
    )
    await gateway_limits.release_reservations(reservation_ids=context.reservation_ids, db=db)
    if context.resolved is not None:
        if record_usage:
            await gateway_accounting.record_proxy_request(
                resolved=context.resolved,
                gateway_request_id=context.gateway_request_id,
                route_attempt_id=context.route_attempt_id,
                http_status=403,
                latency_ms=_elapsed_ms(context.started_at),
                usage=unknown_usage(),
                error_code="access_denied",
                gateway_endpoint=context.gateway_endpoint,
                db=db,
            )
        await _finalize_route_attempt_if_present(
            context=context,
            status_="blocked",
            http_status=403,
            error_code="access_denied",
            db=db,
        )
        await gateway_tracing.finalize_gateway_request(
            gateway_request_id=context.gateway_request_id,
            resolved=context.resolved,
            http_status=403,
            attempt_count=context.attempt_count,
            fallback_attempted=context.fallback_attempted,
            error_code="access_denied",
            db=db,
            final_route_attempt_id=context.route_attempt_id,
            gateway_endpoint=context.gateway_endpoint,
        )
        await gateway_accounting.record_proxy_activity(
            resolved=context.resolved,
            action="proxy.denied",
            message=message,
            severity="warning",
            metadata={"reason": "access_denied"},
            gateway_request_id=context.gateway_request_id,
            db=db,
        )
    else:
        await gateway_tracing.finalize_gateway_request(
            gateway_request_id=context.gateway_request_id,
            resolved=None,
            http_status=403,
            attempt_count=0,
            fallback_attempted=False,
            error_code="access_denied",
            db=db,
            gateway_endpoint=context.gateway_endpoint,
        )


async def finalize_request_guardrail_denied(
    *,
    context: GatewayFailureContext,
    denial: gateway_guardrails.GatewayGuardrailDenied,
    record_usage: bool,
    db: AsyncSession,
) -> None:
    _record_denial(
        denial_type="request_guardrail_denied",
        gateway_endpoint=context.gateway_endpoint,
        phase="request",
    )
    await gateway_limits.release_reservations(reservation_ids=context.reservation_ids, db=db)
    if context.resolved is not None:
        if record_usage:
            await gateway_accounting.record_proxy_request(
                resolved=context.resolved,
                gateway_request_id=context.gateway_request_id,
                route_attempt_id=context.route_attempt_id,
                http_status=403,
                latency_ms=_elapsed_ms(context.started_at),
                usage=unknown_usage(),
                error_code="guardrail_denied",
                gateway_endpoint=context.gateway_endpoint,
                db=db,
            )
        await _finalize_route_attempt_if_present(
            context=context,
            status_="blocked",
            http_status=403,
            error_code="guardrail_denied",
            db=db,
        )
        await gateway_tracing.finalize_gateway_request(
            gateway_request_id=context.gateway_request_id,
            resolved=context.resolved,
            http_status=403,
            attempt_count=context.attempt_count,
            fallback_attempted=context.fallback_attempted,
            error_code="guardrail_denied",
            db=db,
            final_route_attempt_id=context.route_attempt_id,
            gateway_endpoint=context.gateway_endpoint,
        )
        await gateway_accounting.record_proxy_activity(
            resolved=context.resolved,
            action="proxy.guardrail_denied",
            message=denial.detail,
            severity="warning",
            metadata={
                "reason": "guardrail_denied",
                "policy_id": str(denial.policy_id) if denial.policy_id else None,
                "rule_id": str(denial.rule_id) if denial.rule_id else None,
            },
            gateway_request_id=context.gateway_request_id,
            db=db,
        )


async def finalize_streaming_response_guardrail_blocked(
    *,
    context: GatewayFailureContext,
    db: AsyncSession,
) -> None:
    _record_denial(
        denial_type="streaming_response_guardrail_blocked",
        gateway_endpoint=context.gateway_endpoint,
        phase="response",
    )
    await gateway_limits.release_reservations(reservation_ids=context.reservation_ids, db=db)
    await _finalize_route_attempt_if_present(
        context=context,
        status_="blocked",
        http_status=400,
        error_code="streaming_response_guardrail_unsupported",
        db=db,
    )
    await gateway_tracing.finalize_gateway_request(
        gateway_request_id=context.gateway_request_id,
        resolved=context.resolved,
        http_status=400,
        attempt_count=context.attempt_count,
        fallback_attempted=context.fallback_attempted,
        error_code="streaming_response_guardrail_unsupported",
        db=db,
        final_route_attempt_id=context.route_attempt_id,
        gateway_endpoint=context.gateway_endpoint,
    )


async def finalize_provider_unavailable(
    *,
    context: GatewayFailureContext,
    message: str,
    db: AsyncSession,
) -> None:
    _record_denial(
        denial_type="provider_unavailable",
        gateway_endpoint=context.gateway_endpoint,
        phase="provider",
    )
    await gateway_limits.release_reservations(reservation_ids=context.reservation_ids, db=db)
    if context.resolved is not None:
        await gateway_accounting.record_proxy_request(
            resolved=context.resolved,
            gateway_request_id=context.gateway_request_id,
            route_attempt_id=context.route_attempt_id,
            http_status=502,
            latency_ms=_elapsed_ms(context.started_at),
            usage=unknown_usage(),
            error_code="provider_unavailable",
            gateway_endpoint=context.gateway_endpoint,
            db=db,
        )
        await _finalize_route_attempt_if_present(
            context=context,
            status_="failed",
            http_status=502,
            error_code="provider_unavailable",
            db=db,
        )
        await gateway_tracing.finalize_gateway_request(
            gateway_request_id=context.gateway_request_id,
            resolved=context.resolved,
            http_status=502,
            attempt_count=context.attempt_count,
            fallback_attempted=context.fallback_attempted,
            error_code="provider_unavailable",
            db=db,
            final_route_attempt_id=context.route_attempt_id,
            gateway_endpoint=context.gateway_endpoint,
        )
        await gateway_accounting.record_proxy_activity(
            resolved=context.resolved,
            action="proxy.provider_unavailable",
            message=message,
            severity="error",
            metadata={"reason": "provider_unavailable"},
            gateway_request_id=context.gateway_request_id,
            db=db,
        )


async def finalize_provider_upstream_error(
    *,
    context: GatewayFailureContext,
    error: ProviderUpstreamError,
    unavailable_message: str,
    fallback_exhausted_message: str | None,
    upstream_failed_message: str,
    finalize_route_attempt: bool,
    activity_action: str = "proxy.upstream_failed",
    provider_error_metadata: dict[str, Any] | None = None,
    db: AsyncSession,
) -> None:
    _record_denial(
        denial_type="provider_upstream_error",
        gateway_endpoint=context.gateway_endpoint,
        phase="provider",
    )
    if context.resolved is not None:
        await gateway_accounting.record_proxy_request(
            resolved=context.resolved,
            gateway_request_id=context.gateway_request_id,
            route_attempt_id=context.route_attempt_id,
            http_status=error.status_code,
            latency_ms=_elapsed_ms(context.started_at),
            usage=unknown_usage(),
            error_code="provider_upstream_error",
            routing_attempt_index=context.selected_attempt_index,
            attempt_failure_reason=error.failure_reason,
            gateway_endpoint=context.gateway_endpoint,
            db=db,
        )
        if finalize_route_attempt:
            await _finalize_route_attempt_if_present(
                context=context,
                status_="failed",
                http_status=error.status_code,
                error_code="provider_upstream_error",
                failure_reason=error.failure_reason,
                db=db,
            )
        await gateway_tracing.finalize_gateway_request(
            gateway_request_id=context.gateway_request_id,
            resolved=context.resolved,
            http_status=error.status_code,
            attempt_count=context.attempt_count,
            fallback_attempted=context.fallback_attempted,
            error_code="provider_upstream_error",
            db=db,
            final_route_attempt_id=context.route_attempt_id,
            gateway_endpoint=context.gateway_endpoint,
        )
        if context.fallback_attempted and fallback_exhausted_message is not None:
            await gateway_accounting.record_proxy_activity(
                resolved=context.resolved,
                action="proxy.routing_fallback_exhausted",
                message=fallback_exhausted_message,
                severity="error",
                metadata={
                    "reason": error.failure_reason,
                    "http_status": error.status_code,
                },
                gateway_request_id=context.gateway_request_id,
                db=db,
            )
        await gateway_accounting.record_proxy_activity(
            resolved=context.resolved,
            action=activity_action,
            message=upstream_failed_message or unavailable_message,
            severity="error",
            metadata=provider_error_metadata
            or {
                "reason": "provider_upstream_error",
                "http_status": error.status_code,
            },
            gateway_request_id=context.gateway_request_id,
            db=db,
        )
    await gateway_limits.release_reservations(reservation_ids=context.reservation_ids, db=db)


async def _finalize_route_attempt_if_present(
    *,
    context: GatewayFailureContext,
    status_: str,
    http_status: int,
    error_code: str,
    db: AsyncSession,
    failure_reason: str | None = None,
) -> None:
    if context.route_attempt_id is None:
        return
    await gateway_tracing.finalize_gateway_route_attempt(
        route_attempt_id=context.route_attempt_id,
        status_=status_,
        http_status=http_status,
        error_code=error_code,
        failure_reason=failure_reason,
        latency_ms=_elapsed_ms(context.started_at),
        usage=unknown_usage(),
        cost_cents=None,
        cost_micro_cents=None,
        db=db,
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _record_denial(
    *,
    denial_type: str,
    gateway_endpoint: str | None = None,
    phase: str,
) -> None:
    record_gateway_denial(
        denial_type=denial_type,
        gateway_endpoint=gateway_endpoint,
        phase=phase,
    )
    add_span_event(
        "bab.gateway.denial",
        {
            "bab.gateway.phase": phase,
            "bab.gateway.endpoint": gateway_endpoint,
            "bab.gateway.error_code": denial_type,
        },
    )
