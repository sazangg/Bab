from dataclasses import dataclass, field
from time import perf_counter
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.metrics import record_gateway_provider_attempt
from app.core.observability import outcome_for_status
from app.core.tracing import start_span
from app.modules.gateway import accounting as gateway_accounting
from app.modules.gateway import guardrails as gateway_guardrails
from app.modules.gateway import limits as gateway_limits
from app.modules.gateway import tracing as gateway_tracing
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.keys.errors import AccessDeniedError
from app.modules.keys.schemas import ResolvedAccess, ResolvedAccessPlan
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import ProviderUpstreamError
from app.modules.providers.schemas import (
    ProviderAnthropicMessagesRequest,
    ProviderAnthropicMessagesResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
)
from app.modules.usage.accounting import estimate_request_tokens, unknown_usage

logger = structlog.get_logger(__name__)


@dataclass
class ProviderExecutionState:
    resolved: ResolvedAccess | None = None
    reservation_ids: list[UUID] = field(default_factory=list)
    current_route_attempt_id: UUID | None = None
    final_route_attempt_id: UUID | None = None
    attempted_routes: int = 0
    selected_attempt_index: int = 0
    fallback_attempted: bool = False


@dataclass(frozen=True)
class ProviderExecutionResult:
    resolved: ResolvedAccess
    upstream: ProviderChatCompletionResponse
    reservation_ids: list[UUID]
    final_route_attempt_id: UUID | None
    attempted_routes: int
    selected_attempt_index: int
    fallback_attempted: bool


@dataclass(frozen=True)
class NativeAnthropicExecutionResult:
    resolved: ResolvedAccess
    upstream: ProviderAnthropicMessagesResponse
    reservation_ids: list[UUID]
    guardrail_context: GuardrailEvaluationContext | None
    final_route_attempt_id: UUID | None
    attempted_routes: int
    selected_attempt_index: int
    fallback_attempted: bool


@dataclass(frozen=True)
class ProviderBodyTooLargeError(Exception):
    detail: str = "request body exceeds provider limit"


async def execute_openai_compatible_non_streaming(
    *,
    plan: ResolvedAccessPlan,
    provider_payload: ProviderChatCompletionRequest,
    raw_body: bytes,
    gateway_request_id: UUID | None,
    gateway_endpoint: str,
    started_at: float,
    state: ProviderExecutionState,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> ProviderExecutionResult:
    estimated_tokens = estimate_request_tokens(provider_payload.messages)
    last_upstream_error: ProviderUpstreamError | None = None
    for attempt_index, _attempt in enumerate(plan.attempts):
        resolved = resolved_access_from_attempt(plan=plan, attempt_index=attempt_index)
        state.resolved = resolved
        state.selected_attempt_index = attempt_index
        state.attempted_routes = max(state.attempted_routes, attempt_index + 1)
        state.reservation_ids = []
        state.current_route_attempt_id = await gateway_tracing.record_gateway_route_attempt_started(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            attempt_index=attempt_index,
            db=db,
        )
        try:
            resolved_provider = await providers_facade.get_provider(
                provider_id=resolved.provider_id,
                scope=Scope(org_id=resolved.org_id),
                db=db,
            )
            enforce_provider_body_size(raw_body, resolved_provider.max_body_bytes)
            await gateway_guardrails.evaluate_request_guardrails(
                context=gateway_guardrails.build_guardrail_context(
                    resolved=resolved,
                    provider_payload=provider_payload,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=state.current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                ),
                resolved=resolved,
                db=db,
            )
            state.reservation_ids = await gateway_limits.enforce_limit_policies(
                resolved=resolved,
                estimated_input_tokens=estimated_tokens,
                requested_output_tokens=requested_output_tokens(provider_payload.extra_body),
                limit_types=gateway_limits.ESTIMATED_LIMIT_TYPES,
                gateway_request_id=gateway_request_id,
                route_attempt_id=state.current_route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
            state.reservation_ids.extend(
                await gateway_limits.enforce_limit_policies(
                    resolved=resolved,
                    estimated_input_tokens=estimated_tokens,
                    requested_output_tokens=requested_output_tokens(provider_payload.extra_body),
                    limit_types=gateway_limits.REQUEST_LIMIT_TYPES,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=state.current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    db=db,
                )
            )
            with start_span(
                "bab.gateway.provider_attempt",
                {
                    "bab.gateway.endpoint": gateway_endpoint,
                    "bab.gateway.attempt_index": attempt_index,
                    "bab.gateway.request_id": str(gateway_request_id)
                    if gateway_request_id
                    else None,
                    "bab.gateway.route_attempt_id": str(state.current_route_attempt_id)
                    if state.current_route_attempt_id
                    else None,
                },
            ):
                upstream = await providers_facade.create_chat_completion(
                    provider_id=resolved.provider_id,
                    pool_id=resolved.pool_id,
                    provider_credential_id=resolved.provider_key_id,
                    payload=ProviderChatCompletionRequest(
                        model=resolved.provider_model,
                        messages=provider_payload.messages,
                        extra_body=normalize_provider_extra_body(
                            extra_body=provider_payload.extra_body,
                            provider_model=resolved.provider_model,
                        ),
                    ),
                    scope=Scope(org_id=resolved.org_id),
                    db=db,
                    http_client=http_client,
                )
            logger.info(
                "gateway_provider_attempt_succeeded",
                **_provider_attempt_log_fields(
                    resolved=resolved,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=state.current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    attempt_index=attempt_index,
                ),
                status_code=upstream.status_code,
                outcome=outcome_for_status(upstream.status_code),
                duration_ms=_elapsed_ms(started_at),
            )
            record_gateway_provider_attempt(
                gateway_endpoint=gateway_endpoint,
                status_code=upstream.status_code,
                error_code=None,
                duration_seconds=_elapsed_ms(started_at) / 1000,
            )
            state.selected_attempt_index = attempt_index
            state.final_route_attempt_id = state.current_route_attempt_id
            return ProviderExecutionResult(
                resolved=resolved,
                upstream=upstream,
                reservation_ids=state.reservation_ids,
                final_route_attempt_id=state.final_route_attempt_id,
                attempted_routes=state.attempted_routes,
                selected_attempt_index=state.selected_attempt_index,
                fallback_attempted=state.fallback_attempted,
            )
        except ProviderUpstreamError as exc:
            last_upstream_error = exc
            logger.warning(
                "gateway_provider_attempt_failed",
                **_provider_attempt_log_fields(
                    resolved=resolved,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=state.current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    attempt_index=attempt_index,
                ),
                status_code=exc.status_code,
                outcome=outcome_for_status(exc.status_code),
                error_code="provider_upstream_error",
                failure_reason=exc.failure_reason,
                duration_ms=_elapsed_ms(started_at),
            )
            record_gateway_provider_attempt(
                gateway_endpoint=gateway_endpoint,
                status_code=exc.status_code,
                error_code="provider_upstream_error",
                duration_seconds=_elapsed_ms(started_at) / 1000,
            )
            await gateway_tracing.finalize_gateway_route_attempt(
                route_attempt_id=state.current_route_attempt_id,
                status_="failed",
                http_status=exc.status_code,
                error_code="provider_upstream_error",
                failure_reason=exc.failure_reason,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                cost_cents=None,
                cost_micro_cents=None,
                usage_source="unknown",
                db=db,
            )
            if not should_try_next_route(
                plan=plan,
                attempt_index=attempt_index,
                failure_reason=exc.failure_reason,
            ):
                raise
            state.fallback_attempted = True
            await gateway_accounting.record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                route_attempt_id=state.current_route_attempt_id,
                http_status=exc.status_code,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_upstream_error",
                routing_attempt_index=attempt_index,
                is_final_attempt=False,
                attempt_failure_reason=exc.failure_reason,
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
            await gateway_limits.release_reservations(
                reservation_ids=state.reservation_ids,
                db=db,
            )
            await gateway_accounting.record_proxy_activity(
                resolved=resolved,
                action="proxy.routing_fallback_attempted",
                message="provider request failed; trying the next route candidate.",
                severity="warning",
                metadata={
                    "reason": exc.failure_reason,
                    "http_status": exc.status_code,
                    "route_candidate_id": str(resolved.route_candidate_id)
                    if resolved.route_candidate_id
                    else None,
                },
                gateway_request_id=gateway_request_id,
                db=db,
            )
    assert last_upstream_error is not None
    raise last_upstream_error


async def execute_native_anthropic_non_streaming(
    *,
    plan: ResolvedAccessPlan,
    provider_payload: ProviderAnthropicMessagesRequest,
    raw_body: bytes,
    gateway_request_id: UUID | None,
    gateway_endpoint: str,
    anthropic_version: str,
    started_at: float,
    state: ProviderExecutionState,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
) -> NativeAnthropicExecutionResult:
    estimated_tokens = estimate_request_tokens(provider_payload.messages)
    guardrail_context: GuardrailEvaluationContext | None = None
    guardrail_payload = ProviderChatCompletionRequest(
        model=provider_payload.model,
        messages=provider_payload.messages,
        extra_body=provider_payload.extra_body,
    )
    last_upstream_error: ProviderUpstreamError | None = None
    for attempt_index, _attempt in enumerate(plan.attempts):
        resolved = resolved_access_from_attempt(plan=plan, attempt_index=attempt_index)
        state.resolved = resolved
        state.selected_attempt_index = attempt_index
        state.attempted_routes = max(state.attempted_routes, attempt_index + 1)
        state.reservation_ids = []
        state.current_route_attempt_id = await gateway_tracing.record_gateway_route_attempt_started(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            attempt_index=attempt_index,
            db=db,
        )
        try:
            resolved_provider = await providers_facade.get_provider(
                provider_id=resolved.provider_id,
                scope=Scope(org_id=resolved.org_id),
                db=db,
            )
            if not resolved_provider.integration_capabilities.get("native_anthropic_messages"):
                raise AccessDeniedError
            enforce_provider_body_size(raw_body, resolved_provider.max_body_bytes)
            guardrail_context = gateway_guardrails.build_guardrail_context(
                resolved=resolved,
                provider_payload=guardrail_payload,
                gateway_request_id=gateway_request_id,
                route_attempt_id=state.current_route_attempt_id,
                gateway_endpoint=gateway_endpoint,
            )
            await gateway_guardrails.evaluate_request_guardrails(
                context=guardrail_context,
                resolved=resolved,
                db=db,
            )
            state.reservation_ids = await gateway_limits.enforce_limit_policies(
                resolved=resolved,
                estimated_input_tokens=estimated_tokens,
                requested_output_tokens=requested_output_tokens(provider_payload.extra_body),
                limit_types=gateway_limits.ESTIMATED_LIMIT_TYPES,
                gateway_request_id=gateway_request_id,
                route_attempt_id=state.current_route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
            state.reservation_ids.extend(
                await gateway_limits.enforce_limit_policies(
                    resolved=resolved,
                    estimated_input_tokens=estimated_tokens,
                    requested_output_tokens=requested_output_tokens(provider_payload.extra_body),
                    limit_types=gateway_limits.REQUEST_LIMIT_TYPES,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=state.current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    db=db,
                )
            )
            with start_span(
                "bab.gateway.provider_attempt",
                {
                    "bab.gateway.endpoint": gateway_endpoint,
                    "bab.gateway.attempt_index": attempt_index,
                    "bab.gateway.request_id": str(gateway_request_id)
                    if gateway_request_id
                    else None,
                    "bab.gateway.route_attempt_id": str(state.current_route_attempt_id)
                    if state.current_route_attempt_id
                    else None,
                },
            ):
                upstream = await providers_facade.create_anthropic_message(
                    provider_id=resolved.provider_id,
                    pool_id=resolved.pool_id,
                    provider_credential_id=resolved.provider_key_id,
                    payload=ProviderAnthropicMessagesRequest(
                        model=resolved.provider_model,
                        messages=provider_payload.messages,
                        extra_body=provider_payload.extra_body,
                    ),
                    anthropic_version=anthropic_version,
                    scope=Scope(org_id=resolved.org_id),
                    db=db,
                    http_client=http_client,
                )
            logger.info(
                "gateway_provider_attempt_succeeded",
                **_provider_attempt_log_fields(
                    resolved=resolved,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=state.current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    attempt_index=attempt_index,
                ),
                status_code=upstream.status_code,
                outcome=outcome_for_status(upstream.status_code),
                duration_ms=_elapsed_ms(started_at),
            )
            record_gateway_provider_attempt(
                gateway_endpoint=gateway_endpoint,
                status_code=upstream.status_code,
                error_code=None,
                duration_seconds=_elapsed_ms(started_at) / 1000,
            )
            state.final_route_attempt_id = state.current_route_attempt_id
            return NativeAnthropicExecutionResult(
                resolved=resolved,
                upstream=upstream,
                reservation_ids=state.reservation_ids,
                guardrail_context=guardrail_context,
                final_route_attempt_id=state.final_route_attempt_id,
                attempted_routes=state.attempted_routes,
                selected_attempt_index=state.selected_attempt_index,
                fallback_attempted=state.fallback_attempted,
            )
        except ProviderUpstreamError as exc:
            last_upstream_error = exc
            logger.warning(
                "gateway_provider_attempt_failed",
                **_provider_attempt_log_fields(
                    resolved=resolved,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=state.current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    attempt_index=attempt_index,
                ),
                status_code=exc.status_code,
                outcome=outcome_for_status(exc.status_code),
                error_code="provider_upstream_error",
                failure_reason=exc.failure_reason,
                duration_ms=_elapsed_ms(started_at),
            )
            record_gateway_provider_attempt(
                gateway_endpoint=gateway_endpoint,
                status_code=exc.status_code,
                error_code="provider_upstream_error",
                duration_seconds=_elapsed_ms(started_at) / 1000,
            )
            await gateway_tracing.finalize_gateway_route_attempt(
                route_attempt_id=state.current_route_attempt_id,
                status_="failed",
                http_status=exc.status_code,
                error_code="provider_upstream_error",
                failure_reason=exc.failure_reason,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                cost_cents=None,
                cost_micro_cents=None,
                usage_source="unknown",
                db=db,
            )
            if not should_try_next_route(
                plan=plan,
                attempt_index=attempt_index,
                failure_reason=exc.failure_reason,
            ):
                raise
            state.fallback_attempted = True
            await gateway_accounting.record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                route_attempt_id=state.current_route_attempt_id,
                http_status=exc.status_code,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_upstream_error",
                routing_attempt_index=attempt_index,
                is_final_attempt=False,
                attempt_failure_reason=exc.failure_reason,
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
            await gateway_limits.release_reservations(
                reservation_ids=state.reservation_ids,
                db=db,
            )
            await gateway_accounting.record_proxy_activity(
                resolved=resolved,
                action="proxy.routing_fallback_attempted",
                message="Native Anthropic provider failed; trying the next route candidate.",
                severity="warning",
                metadata={
                    "reason": exc.failure_reason,
                    "http_status": exc.status_code,
                    "route_candidate_id": str(resolved.route_candidate_id)
                    if resolved.route_candidate_id
                    else None,
                },
                gateway_request_id=gateway_request_id,
                db=db,
            )
    assert last_upstream_error is not None
    raise last_upstream_error


def enforce_provider_body_size(raw_body: bytes, max_body_bytes: int | None) -> None:
    if max_body_bytes is not None and len(raw_body) > max_body_bytes:
        raise ProviderBodyTooLargeError()


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _provider_attempt_log_fields(
    *,
    resolved: ResolvedAccess,
    gateway_request_id: UUID | None,
    route_attempt_id: UUID | None,
    gateway_endpoint: str,
    attempt_index: int,
) -> dict[str, object]:
    return {
        "gateway_request_id": str(gateway_request_id) if gateway_request_id else None,
        "route_attempt_id": str(route_attempt_id) if route_attempt_id else None,
        "org_id": str(resolved.org_id),
        "team_id": str(resolved.team_id) if resolved.team_id else None,
        "project_id": str(resolved.project_id) if resolved.project_id else None,
        "virtual_key_id": str(resolved.virtual_key_id),
        "provider_id": str(resolved.provider_id),
        "credential_pool_id": str(resolved.pool_id),
        "provider_credential_id": str(resolved.provider_key_id)
        if resolved.provider_key_id
        else None,
        "model_offering_id": str(resolved.model_offering_id),
        "requested_model": resolved.requested_model,
        "public_model_name": resolved.public_model_name,
        "provider_model": resolved.provider_model,
        "gateway_endpoint": gateway_endpoint,
        "attempt_index": attempt_index,
    }


def requested_output_tokens(extra_body: dict) -> int | None:
    value = extra_body.get("max_tokens") or extra_body.get("max_completion_tokens")
    if isinstance(value, int) and value > 0:
        return value
    return None


def normalize_provider_extra_body(
    *,
    extra_body: dict,
    provider_model: str,
) -> dict:
    normalized = dict(extra_body)
    if (
        uses_completion_token_limit(provider_model)
        and "max_tokens" in normalized
        and "max_completion_tokens" not in normalized
    ):
        normalized["max_completion_tokens"] = normalized.pop("max_tokens")
    return normalized


def uses_completion_token_limit(provider_model: str) -> bool:
    normalized_model = provider_model.lower()
    return normalized_model.startswith(("gpt-5", "o1", "o3", "o4"))


def should_try_next_route(
    *,
    plan: ResolvedAccessPlan,
    attempt_index: int,
    failure_reason: str,
) -> bool:
    if plan.provider_pinned or plan.fallback_disabled_reason is not None:
        return False
    if plan.routing_mode != "ordered_fallback":
        return False
    if failure_reason not in set(plan.fallback_on):
        return False
    return attempt_index + 1 < len(plan.attempts)


def resolved_access_from_attempt(
    *,
    plan: ResolvedAccessPlan,
    attempt_index: int,
) -> ResolvedAccess:
    attempt = plan.attempts[attempt_index]
    return ResolvedAccess(
        org_id=attempt.org_id,
        team_id=attempt.team_id,
        project_id=attempt.project_id,
        access_policy_id=attempt.access_policy_id,
        access_policy_revision_id=attempt.access_policy_revision_id,
        access_policy_assignment_id=attempt.access_policy_assignment_id,
        access_policy_route_id=attempt.access_policy_route_id,
        public_model_id=attempt.public_model_id,
        route_candidate_id=attempt.route_candidate_id,
        primary_route_candidate_id=attempt.primary_route_candidate_id,
        public_model_name=attempt.public_model_name,
        routing_mode=attempt.routing_mode,
        model_offering_id=attempt.model_offering_id,
        limit_policy_ids=attempt.limit_policy_ids,
        limit_policies=attempt.limit_policies,
        virtual_key_id=attempt.virtual_key_id,
        provider_id=attempt.provider_id,
        pool_id=attempt.pool_id,
        provider_key_id=attempt.provider_key_id,
        requested_model=attempt.requested_model,
        provider_model=attempt.provider_model,
        input_price_per_million_tokens=attempt.input_price_per_million_tokens,
        output_price_per_million_tokens=attempt.output_price_per_million_tokens,
        fallback_disabled_reason=plan.fallback_disabled_reason,
    )
