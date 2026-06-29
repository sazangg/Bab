from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import record_gateway_denial
from app.core.tracing import add_span_event
from app.modules.gateway import accounting as gateway_accounting
from app.modules.gateway import costing as gateway_costing
from app.modules.gateway import guardrails as gateway_guardrails
from app.modules.gateway import limits as gateway_limits
from app.modules.gateway import tracing as gateway_tracing
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.keys.schemas import ResolvedAccess
from app.modules.providers.schemas import (
    ProviderAnthropicMessagesRequest,
    ProviderAnthropicMessagesResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
)
from app.modules.usage.accounting import usage_from_provider_response


@dataclass(frozen=True)
class FinalizedNonStreamingResponse:
    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class GatewayResponseGuardrailDeniedError(Exception):
    detail: str


async def finalize_openai_compatible_non_streaming_response(
    *,
    resolved: ResolvedAccess,
    provider_payload: ProviderChatCompletionRequest,
    upstream: ProviderChatCompletionResponse,
    gateway_request_id: UUID | None,
    final_route_attempt_id: UUID | None,
    reservation_ids: list[UUID],
    selected_attempt_index: int,
    attempted_routes: int,
    fallback_attempted: bool,
    gateway_endpoint: str,
    started_at: float,
    db: AsyncSession,
) -> FinalizedNonStreamingResponse:
    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    try:
        await gateway_guardrails.evaluate_response_guardrails(
            context=gateway_guardrails.build_guardrail_context(
                resolved=resolved,
                provider_payload=provider_payload,
                gateway_request_id=gateway_request_id,
                route_attempt_id=final_route_attempt_id,
                gateway_endpoint=gateway_endpoint,
            ),
            resolved=resolved,
            response_text=_response_text(upstream.body),
            db=db,
        )
    except gateway_guardrails.GatewayGuardrailDenied as exc:
        record_gateway_denial(
            denial_type="response_guardrail_denied",
            gateway_endpoint=gateway_endpoint,
            phase="response",
        )
        add_span_event(
            "bab.gateway.denial",
            {
                "bab.gateway.phase": "response",
                "bab.gateway.endpoint": gateway_endpoint,
                "bab.gateway.error_code": "response_guardrail_denied",
            },
        )
        actual_cost_cents = await gateway_accounting.record_proxy_request(
            resolved=resolved,
            gateway_request_id=gateway_request_id,
            route_attempt_id=final_route_attempt_id,
            http_status=403,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code="guardrail_output_denied",
            provider_credential_id=upstream.provider_credential_id,
            routing_attempt_index=selected_attempt_index,
            gateway_endpoint=gateway_endpoint,
            db=db,
        )
        actual_cost_micro_cents = gateway_costing.calculate_cost_micro_cents(
            resolved=resolved,
            usage=usage,
        )
        await gateway_tracing.finalize_gateway_route_attempt(
            route_attempt_id=final_route_attempt_id,
            status_="blocked",
            http_status=403,
            error_code="guardrail_output_denied",
            failure_reason=None,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            cost_cents=actual_cost_cents,
            cost_micro_cents=actual_cost_micro_cents,
            usage_source=usage.usage_source,
            db=db,
        )
        await gateway_tracing.finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            http_status=403,
            attempt_count=attempted_routes or 1,
            fallback_attempted=fallback_attempted,
            error_code="guardrail_output_denied",
            db=db,
            final_route_attempt_id=final_route_attempt_id,
            gateway_endpoint=gateway_endpoint,
        )
        await gateway_limits.commit_reservations(
            reservation_ids=reservation_ids,
            usage=usage,
            cost_cents=actual_cost_cents,
            cost_micro_cents=actual_cost_micro_cents,
            db=db,
        )
        await gateway_accounting.record_proxy_activity(
            resolved=resolved,
            action="proxy.guardrail_output_denied",
            message=exc.detail,
            severity="warning",
            metadata={
                "reason": "guardrail_output_denied",
                "policy_id": str(exc.policy_id) if exc.policy_id else None,
                "rule_id": str(exc.rule_id) if exc.rule_id else None,
            },
            gateway_request_id=gateway_request_id,
            db=db,
        )
        raise GatewayResponseGuardrailDeniedError(detail=exc.detail) from exc

    actual_cost_cents = await gateway_accounting.record_proxy_request(
        resolved=resolved,
        gateway_request_id=gateway_request_id,
        route_attempt_id=final_route_attempt_id,
        http_status=upstream.status_code,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        error_code=None,
        provider_credential_id=upstream.provider_credential_id,
        routing_attempt_index=selected_attempt_index,
        gateway_endpoint=gateway_endpoint,
        db=db,
    )
    actual_cost_micro_cents = gateway_costing.calculate_cost_micro_cents(
        resolved=resolved,
        usage=usage,
    )
    await gateway_tracing.finalize_gateway_route_attempt(
        route_attempt_id=final_route_attempt_id,
        status_="succeeded",
        http_status=upstream.status_code,
        error_code=None,
        failure_reason=None,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        cost_cents=actual_cost_cents,
        cost_micro_cents=actual_cost_micro_cents,
        usage_source=usage.usage_source,
        db=db,
    )
    await gateway_tracing.finalize_gateway_request(
        gateway_request_id=gateway_request_id,
        resolved=resolved,
        http_status=upstream.status_code,
        attempt_count=attempted_routes or 1,
        fallback_attempted=fallback_attempted,
        error_code=None,
        db=db,
        final_route_attempt_id=final_route_attempt_id,
        gateway_endpoint=gateway_endpoint,
    )
    if fallback_attempted:
        await gateway_accounting.record_proxy_activity(
            resolved=resolved,
            action="proxy.routing_fallback_succeeded",
            message="provider request succeeded after fallback.",
            severity="info",
            metadata={
                "attempt_count": attempted_routes,
                "route_candidate_id": str(resolved.route_candidate_id)
                if resolved.route_candidate_id
                else None,
            },
            gateway_request_id=gateway_request_id,
            db=db,
        )
    await gateway_limits.commit_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=actual_cost_cents,
        cost_micro_cents=actual_cost_micro_cents,
        db=db,
    )
    return FinalizedNonStreamingResponse(status_code=upstream.status_code, body=upstream.body)


async def finalize_native_anthropic_non_streaming_response(
    *,
    resolved: ResolvedAccess,
    provider_payload: ProviderAnthropicMessagesRequest,
    upstream: ProviderAnthropicMessagesResponse,
    guardrail_context: GuardrailEvaluationContext | None,
    gateway_request_id: UUID | None,
    final_route_attempt_id: UUID | None,
    reservation_ids: list[UUID],
    selected_attempt_index: int,
    attempted_routes: int,
    fallback_attempted: bool,
    started_at: float,
    db: AsyncSession,
) -> FinalizedNonStreamingResponse:
    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    try:
        await gateway_guardrails.evaluate_response_guardrails(
            context=guardrail_context
            or gateway_guardrails.build_guardrail_context(
                resolved=resolved,
                provider_payload=ProviderChatCompletionRequest(
                    model=provider_payload.model,
                    messages=provider_payload.messages,
                    extra_body=provider_payload.extra_body,
                ),
                gateway_request_id=gateway_request_id,
                route_attempt_id=final_route_attempt_id,
                gateway_endpoint="anthropic_messages",
            ),
            resolved=resolved,
            response_text=_response_text(upstream.body),
            db=db,
        )
    except gateway_guardrails.GatewayGuardrailDenied as exc:
        record_gateway_denial(
            denial_type="response_guardrail_denied",
            gateway_endpoint="anthropic_messages",
            phase="response",
        )
        add_span_event(
            "bab.gateway.denial",
            {
                "bab.gateway.phase": "response",
                "bab.gateway.endpoint": "anthropic_messages",
                "bab.gateway.error_code": "response_guardrail_denied",
            },
        )
        actual_cost_cents = await gateway_accounting.record_proxy_request(
            resolved=resolved,
            gateway_request_id=gateway_request_id,
            route_attempt_id=final_route_attempt_id,
            http_status=403,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code="guardrail_output_denied",
            provider_credential_id=upstream.provider_credential_id,
            routing_attempt_index=selected_attempt_index,
            gateway_endpoint="anthropic_messages",
            db=db,
        )
        actual_cost_micro_cents = gateway_costing.calculate_cost_micro_cents(
            resolved=resolved,
            usage=usage,
        )
        await gateway_tracing.finalize_gateway_route_attempt(
            route_attempt_id=final_route_attempt_id,
            status_="blocked",
            http_status=403,
            error_code="guardrail_output_denied",
            failure_reason=None,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            cost_cents=actual_cost_cents,
            cost_micro_cents=actual_cost_micro_cents,
            usage_source=usage.usage_source,
            db=db,
        )
        await gateway_tracing.finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            http_status=403,
            attempt_count=attempted_routes or 1,
            fallback_attempted=fallback_attempted,
            error_code="guardrail_output_denied",
            db=db,
            final_route_attempt_id=final_route_attempt_id,
            gateway_endpoint="anthropic_messages",
        )
        await gateway_limits.commit_reservations(
            reservation_ids=reservation_ids,
            usage=usage,
            cost_cents=actual_cost_cents,
            cost_micro_cents=actual_cost_micro_cents,
            db=db,
        )
        await gateway_accounting.record_proxy_activity(
            resolved=resolved,
            action="proxy.guardrail_output_denied",
            message=exc.detail,
            severity="warning",
            metadata={
                "reason": "guardrail_output_denied",
                "policy_id": str(exc.policy_id) if exc.policy_id else None,
                "rule_id": str(exc.rule_id) if exc.rule_id else None,
            },
            gateway_request_id=gateway_request_id,
            db=db,
        )
        raise GatewayResponseGuardrailDeniedError(detail=exc.detail) from exc

    actual_cost_cents = await gateway_accounting.record_proxy_request(
        resolved=resolved,
        gateway_request_id=gateway_request_id,
        route_attempt_id=final_route_attempt_id,
        http_status=upstream.status_code,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        error_code=None,
        provider_credential_id=upstream.provider_credential_id,
        routing_attempt_index=selected_attempt_index,
        gateway_endpoint="anthropic_messages",
        db=db,
    )
    actual_cost_micro_cents = gateway_costing.calculate_cost_micro_cents(
        resolved=resolved,
        usage=usage,
    )
    await gateway_tracing.finalize_gateway_route_attempt(
        route_attempt_id=final_route_attempt_id,
        status_="succeeded",
        http_status=upstream.status_code,
        error_code=None,
        failure_reason=None,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        cost_cents=actual_cost_cents,
        cost_micro_cents=actual_cost_micro_cents,
        usage_source=usage.usage_source,
        db=db,
    )
    await gateway_tracing.finalize_gateway_request(
        gateway_request_id=gateway_request_id,
        resolved=resolved,
        http_status=upstream.status_code,
        attempt_count=attempted_routes or 1,
        fallback_attempted=fallback_attempted,
        error_code=None,
        db=db,
        final_route_attempt_id=final_route_attempt_id,
        gateway_endpoint="anthropic_messages",
    )
    if fallback_attempted:
        await gateway_accounting.record_proxy_activity(
            resolved=resolved,
            action="proxy.routing_fallback_succeeded",
            message="Native Anthropic request succeeded after fallback.",
            severity="info",
            metadata={
                "attempt_count": attempted_routes,
                "route_candidate_id": str(resolved.route_candidate_id)
                if resolved.route_candidate_id
                else None,
            },
            gateway_request_id=gateway_request_id,
            db=db,
        )
    await gateway_limits.commit_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=actual_cost_cents,
        cost_micro_cents=actual_cost_micro_cents,
        db=db,
    )
    return FinalizedNonStreamingResponse(status_code=upstream.status_code, body=upstream.body)


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _response_text(response_body: dict[str, Any]) -> str:
    choices = response_body.get("choices") if isinstance(response_body, dict) else None
    parts: list[str] = []
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                parts.append(_content_to_text(message.get("content")))
                continue
            text = choice.get("text")
            if isinstance(text, str):
                parts.append(text)
    if isinstance(response_body, dict):
        content = response_body.get("content")
        if content is not None:
            parts.append(_content_to_text(content))
        output_text = response_body.get("output_text")
        if isinstance(output_text, str):
            parts.append(output_text)
    return "\n".join(part for part in parts if part)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_content_to_text(part) for part in content)
    if isinstance(content, dict):
        value = content.get("text")
        return value if isinstance(value, str) else ""
    return str(content)
