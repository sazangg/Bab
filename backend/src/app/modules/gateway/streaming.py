import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.gateway import accounting as gateway_accounting
from app.modules.gateway import costing as gateway_costing
from app.modules.gateway import guardrails as gateway_guardrails
from app.modules.gateway import limits as gateway_limits
from app.modules.gateway import provider_execution as gateway_provider_execution
from app.modules.gateway import tracing as gateway_tracing
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.keys.errors import AccessDeniedError
from app.modules.keys.schemas import ResolvedAccess, ResolvedAccessPlan
from app.modules.providers import facade as providers_facade
from app.modules.providers.schemas import (
    ProviderChatCompletionRequest,
    ProviderChatCompletionStream,
)
from app.modules.usage.accounting import (
    estimate_request_tokens,
    usage_from_stream_chunks,
)


@dataclass(frozen=True)
class StreamingExecutionResult:
    resolved: ResolvedAccess
    upstream: ProviderChatCompletionStream
    provider_payload: ProviderChatCompletionRequest
    guardrail_context: GuardrailEvaluationContext
    reservation_ids: list[UUID]
    route_attempt_id: UUID | None


@dataclass(frozen=True)
class StreamingBlockedByResponseGuardrailError(Exception):
    detail: str = "streaming is disabled when enforced output guardrails apply"


async def prepare_openai_compatible_streaming(
    *,
    plan: ResolvedAccessPlan,
    provider_payload: ProviderChatCompletionRequest,
    raw_body: bytes,
    provider_id: UUID | None,
    gateway_request_id: UUID | None,
    state: gateway_provider_execution.ProviderExecutionState,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> StreamingExecutionResult:
    resolved = gateway_provider_execution.resolved_access_from_attempt(plan=plan, attempt_index=0)
    state.resolved = resolved
    state.selected_attempt_index = 0
    state.attempted_routes = 1
    if provider_id is not None and provider_id != resolved.provider_id:
        raise AccessDeniedError
    resolved_provider = await providers_facade.get_provider(
        provider_id=resolved.provider_id,
        scope=Scope(org_id=resolved.org_id),
        db=db,
    )
    gateway_provider_execution.enforce_provider_body_size(
        raw_body,
        resolved_provider.max_body_bytes,
    )
    route_attempt_id = await gateway_tracing.record_gateway_route_attempt_started(
        gateway_request_id=gateway_request_id,
        resolved=resolved,
        attempt_index=0,
        db=db,
    )
    state.current_route_attempt_id = route_attempt_id
    estimated_tokens = estimate_request_tokens(provider_payload.messages)
    state.reservation_ids = await gateway_limits.enforce_limit_policies(
        resolved=resolved,
        estimated_input_tokens=estimated_tokens,
        requested_output_tokens=gateway_provider_execution.requested_output_tokens(
            provider_payload.extra_body
        ),
        limit_types=gateway_limits.ESTIMATED_LIMIT_TYPES,
        gateway_request_id=gateway_request_id,
        route_attempt_id=route_attempt_id,
        gateway_endpoint="chat_completions",
        db=db,
    )
    reservation_ids = state.reservation_ids
    guardrail_context = gateway_guardrails.build_guardrail_context(
        resolved=resolved,
        provider_payload=provider_payload,
        gateway_request_id=gateway_request_id,
        route_attempt_id=route_attempt_id,
        gateway_endpoint="chat_completions",
    )
    await gateway_guardrails.evaluate_request_guardrails(
        context=guardrail_context,
        resolved=resolved,
        db=db,
    )
    state.reservation_ids.extend(
        await gateway_limits.enforce_limit_policies(
            resolved=resolved,
            estimated_input_tokens=estimated_tokens,
            requested_output_tokens=gateway_provider_execution.requested_output_tokens(
                provider_payload.extra_body
            ),
            limit_types=gateway_limits.REQUEST_LIMIT_TYPES,
            gateway_request_id=gateway_request_id,
            route_attempt_id=route_attempt_id,
            gateway_endpoint="chat_completions",
            db=db,
        )
    )
    reservation_ids = state.reservation_ids
    if resolved.fallback_disabled_reason is not None:
        await gateway_accounting.record_proxy_activity(
            resolved=resolved,
            action="proxy.streaming_fallback_disabled",
            message="Streaming fallback is disabled for this phase.",
            severity="info",
            metadata={"reason": resolved.fallback_disabled_reason},
            gateway_request_id=gateway_request_id,
            db=db,
        )
    if await gateway_guardrails.has_enforced_response_guardrails(
        context=guardrail_context,
        db=db,
    ):
        await gateway_limits.release_reservations(reservation_ids=reservation_ids, db=db)
        raise StreamingBlockedByResponseGuardrailError()
    upstream = await providers_facade.stream_chat_completion(
        provider_id=resolved.provider_id,
        pool_id=resolved.pool_id,
        provider_credential_id=resolved.provider_key_id,
        payload=ProviderChatCompletionRequest(
            model=resolved.provider_model,
            messages=provider_payload.messages,
            extra_body=gateway_provider_execution.normalize_provider_extra_body(
                extra_body=provider_payload.extra_body,
                provider_model=resolved.provider_model,
            ),
        ),
        scope=Scope(org_id=resolved.org_id),
        db=db,
        http_client=http_client,
    )
    return StreamingExecutionResult(
        resolved=resolved,
        upstream=upstream,
        provider_payload=provider_payload,
        guardrail_context=guardrail_context,
        reservation_ids=reservation_ids,
        route_attempt_id=route_attempt_id,
    )


async def stream_openai_compatible_response(
    *,
    result: StreamingExecutionResult,
    started_at: float,
    db: AsyncSession,
) -> AsyncGenerator[bytes]:
    chunks: list[bytes] = []
    error_code: str | None = None
    try:
        async for chunk in result.upstream.chunks:
            chunks.append(chunk)
            yield chunk
    except Exception:
        error_code = "provider_stream_error"
        raise
    finally:
        await result.upstream.close()
        if error_code is None:
            try:
                await gateway_guardrails.evaluate_response_guardrails(
                    context=result.guardrail_context,
                    resolved=result.resolved,
                    response_text=_stream_response_text(chunks),
                    db=db,
                )
            except gateway_guardrails.GatewayGuardrailDenied as exc:
                await gateway_accounting.record_proxy_activity(
                    resolved=result.resolved,
                    action="proxy.guardrail_output_denied",
                    message=exc.detail,
                    severity="warning",
                    metadata={
                        "reason": "guardrail_output_denied",
                        "policy_id": str(exc.policy_id) if exc.policy_id else None,
                        "rule_id": str(exc.rule_id) if exc.rule_id else None,
                        "streaming": True,
                    },
                    gateway_request_id=result.guardrail_context.gateway_request_id,
                    db=db,
                )
        usage = usage_from_stream_chunks(
            request_messages=result.provider_payload.messages,
            chunks=chunks,
        )
        usage_cost_cents = await gateway_accounting.record_proxy_request(
            resolved=result.resolved,
            gateway_request_id=result.guardrail_context.gateway_request_id,
            route_attempt_id=result.route_attempt_id,
            http_status=result.upstream.status_code,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code=error_code,
            provider_credential_id=result.upstream.provider_credential_id,
            gateway_endpoint="chat_completions",
            db=db,
        )
        usage_cost_micro_cents = gateway_costing.calculate_cost_micro_cents(
            resolved=result.resolved,
            usage=usage,
        )
        if error_code is None:
            await gateway_limits.commit_reservations(
                reservation_ids=result.reservation_ids,
                usage=usage,
                cost_cents=usage_cost_cents,
                cost_micro_cents=usage_cost_micro_cents,
                db=db,
            )
            await gateway_tracing.finalize_gateway_route_attempt(
                route_attempt_id=result.route_attempt_id,
                status_="succeeded",
                http_status=result.upstream.status_code,
                error_code=None,
                failure_reason=None,
                latency_ms=_elapsed_ms(started_at),
                usage=usage,
                cost_cents=usage_cost_cents,
                cost_micro_cents=usage_cost_micro_cents,
                usage_source=usage.usage_source,
                db=db,
            )
            await gateway_tracing.finalize_gateway_request(
                gateway_request_id=result.guardrail_context.gateway_request_id,
                resolved=result.resolved,
                http_status=result.upstream.status_code,
                attempt_count=1,
                fallback_attempted=False,
                error_code=None,
                db=db,
                final_route_attempt_id=result.route_attempt_id,
            )
        else:
            await gateway_limits.release_reservations(
                reservation_ids=result.reservation_ids,
                db=db,
            )
            await gateway_tracing.finalize_gateway_route_attempt(
                route_attempt_id=result.route_attempt_id,
                status_="failed",
                http_status=result.upstream.status_code,
                error_code=error_code,
                failure_reason=error_code,
                latency_ms=_elapsed_ms(started_at),
                usage=usage,
                cost_cents=usage_cost_cents,
                cost_micro_cents=usage_cost_micro_cents,
                usage_source=usage.usage_source,
                db=db,
            )
            await gateway_tracing.finalize_gateway_request(
                gateway_request_id=result.guardrail_context.gateway_request_id,
                resolved=result.resolved,
                http_status=result.upstream.status_code,
                attempt_count=1,
                fallback_attempted=False,
                error_code=error_code,
                db=db,
                final_route_attempt_id=result.route_attempt_id,
            )
            await gateway_accounting.record_proxy_activity(
                resolved=result.resolved,
                action="proxy.stream_failed",
                message="provider stream failed after the response started.",
                severity="error",
                metadata={"reason": error_code},
                gateway_request_id=result.guardrail_context.gateway_request_id,
                db=db,
            )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _stream_response_text(chunks: list[bytes]) -> str:
    parts: list[str] = []
    stream_body = b"".join(chunks).decode("utf-8", errors="replace")
    for line in stream_body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        parts.append(_stream_event_text(event))
    return "".join(part for part in parts if part)


def _stream_event_text(event: dict[str, Any]) -> str:
    parts: list[str] = []
    choices = event.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                parts.append(_content_to_text(delta.get("content")))
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                parts.append(_content_to_text(message.get("content")))
                continue
            text = choice.get("text")
            if isinstance(text, str):
                parts.append(text)
    content = event.get("content")
    if content is not None:
        parts.append(_content_to_text(content))
    return "".join(part for part in parts if part)


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
