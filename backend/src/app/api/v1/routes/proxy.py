import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.database import Scope, get_db
from app.core.request_ids import current_request_id
from app.modules.activity import facade as activity_facade
from app.modules.activity.schemas import RecordActivityEvent
from app.modules.guardrails import facade as guardrails_facade
from app.modules.guardrails.errors import GuardrailDeniedError
from app.modules.guardrails.internal import repository as guardrails_repository
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
)
from app.modules.keys.schemas import ResolveAccessRequest, ResolvedAccess, ResolvedAccessPlan
from app.modules.policies.dimensions import (
    ATTEMPT_SCOPED_DIMENSIONS,
    PolicyDimensionStage,
    evaluate_matcher,
    to_dimension_snapshot,
)
from app.modules.policies.internal import repository as policies_repository
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import (
    ProviderAdapterNotFoundError,
    ProviderInactiveError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.schemas import (
    ProviderAnthropicMessagesRequest,
    ProviderChatCompletionRequest,
)
from app.modules.settings import facade as settings_facade
from app.modules.usage import facade as usage_facade
from app.modules.usage.accounting import (
    UsageAccounting,
    estimate_request_tokens,
    subtract_months,
    unknown_usage,
    usage_from_provider_response,
    usage_from_stream_chunks,
)
from app.modules.usage.costing.base import CostingContext
from app.modules.usage.costing.registry import default_cost_calculator_registry
from app.modules.usage.schemas import (
    CreateGatewayRequest,
    FinalizeGatewayRequest,
    RecordLimitPolicyCommittedUsage,
    RecordLimitPolicyReservation,
    RecordUsage,
)

router = APIRouter(prefix="/v1", tags=["proxy"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
VirtualKeyAuthorization = Annotated[str | None, Header(alias="Authorization")]
ProviderIdHeader = Annotated[UUID | None, Header(alias="X-Bab-Provider-Id")]
AnthropicApiKey = Annotated[str | None, Header(alias="x-api-key")]
ESTIMATED_LIMIT_TYPES = {
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tokens_per_request",
    "budget_cents",
}
REQUEST_LIMIT_TYPES = {"requests"}


async def get_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        yield client


ProxyHttpClient = Annotated[httpx.AsyncClient, Depends(get_proxy_http_client)]


@router.get("/models")
async def list_models(
    db: DatabaseSession,
    authorization: VirtualKeyAuthorization = None,
) -> dict[str, Any]:
    raw_key = _extract_bearer_token(authorization)
    try:
        models = await keys_facade.list_accessible_models(raw_key=raw_key, db=db)
    except InvalidVirtualKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no active access policy",
        ) from exc
    return {"object": "list", "data": [model.model_dump(mode="json") for model in models]}


@router.post("/completions", response_model=None)
async def create_completion(
    request: Request,
    db: DatabaseSession,
    http_client: ProxyHttpClient,
    authorization: VirtualKeyAuthorization = None,
    provider_id: ProviderIdHeader = None,
) -> Response:
    started_at = perf_counter()
    raw_body = await _read_body_within_limit(request, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    if body.get("stream") is True:
        raise HTTPException(status_code=400, detail="streaming completions are not supported")
    chat_body = _completion_body_to_chat_body(body)
    return await _execute_chat_proxy(
        body=chat_body,
        raw_body=raw_body,
        started_at=started_at,
        gateway_endpoint="completions",
        db=db,
        http_client=http_client,
        authorization=authorization,
        provider_id=provider_id,
        response_transform=lambda response_body: _chat_response_to_completion(response_body, body),
    )


@router.post("/responses", response_model=None)
async def create_response(
    request: Request,
    db: DatabaseSession,
    http_client: ProxyHttpClient,
    authorization: VirtualKeyAuthorization = None,
    provider_id: ProviderIdHeader = None,
) -> Response:
    started_at = perf_counter()
    raw_body = await _read_body_within_limit(request, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    if body.get("stream") is True:
        raise HTTPException(status_code=400, detail="streaming responses are not supported")
    chat_body = _responses_body_to_chat_body(body)
    return await _execute_chat_proxy(
        body=chat_body,
        raw_body=raw_body,
        started_at=started_at,
        gateway_endpoint="responses",
        db=db,
        http_client=http_client,
        authorization=authorization,
        provider_id=provider_id,
        response_transform=lambda response_body: _chat_response_to_response(response_body, body),
    )


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    request: Request,
    db: DatabaseSession,
    http_client: ProxyHttpClient,
    authorization: VirtualKeyAuthorization = None,
    provider_id: ProviderIdHeader = None,
) -> Response:
    started_at = perf_counter()
    raw_body = await _read_body_within_limit(request, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    is_streaming = body.get("stream") is True
    if not is_streaming:
        return await _execute_chat_proxy(
            body=body,
            raw_body=raw_body,
            started_at=started_at,
            gateway_endpoint="chat_completions",
            db=db,
            http_client=http_client,
            authorization=authorization,
            provider_id=provider_id,
            response_transform=lambda response_body: response_body,
        )

    provider_payload = _to_provider_payload(body)
    raw_key = _extract_bearer_token(authorization)
    resolved = None
    gateway_request_id: UUID | None = None
    estimated_tokens = 0
    reservation_ids: list[UUID] = []
    try:
        gateway_request_id = await _create_gateway_request(
            resolved=None,
            requested_model=provider_payload.model,
            gateway_endpoint="chat_completions",
            db=db,
        )
        resolved = await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=raw_key,
                requested_model=provider_payload.model,
                provider_id=provider_id,
                streaming=is_streaming,
                gateway_endpoint="chat_completions",
            ),
            db=db,
        )
        org_settings = await settings_facade.get_organization_settings(
            scope=Scope(org_id=resolved.org_id),
            db=db,
        )
        _enforce_body_size(raw_body, org_settings.default_max_body_bytes)
        if provider_id is not None and provider_id != resolved.provider_id:
            raise AccessDeniedError
        resolved_provider = await providers_facade.get_provider(
            provider_id=resolved.provider_id,
            scope=Scope(org_id=resolved.org_id),
            db=db,
        )
        _enforce_provider_body_size(raw_body, resolved_provider.max_body_bytes)
        estimated_tokens = estimate_request_tokens(provider_payload.messages)
        reservation_ids = await _enforce_limit_policies(
            resolved=resolved,
            estimated_input_tokens=estimated_tokens,
            requested_output_tokens=_requested_output_tokens(provider_payload.extra_body),
            limit_types=ESTIMATED_LIMIT_TYPES,
            gateway_request_id=gateway_request_id,
            gateway_endpoint="chat_completions",
            db=db,
        )
        guardrail_context = _guardrail_context(
            resolved=resolved,
            provider_payload=provider_payload,
            gateway_request_id=gateway_request_id,
            gateway_endpoint="chat_completions",
        )
        await _evaluate_guardrail_request(
            context=guardrail_context,
            resolved=resolved,
            db=db,
        )
        reservation_ids.extend(
            await _enforce_limit_policies(
                resolved=resolved,
                estimated_input_tokens=estimated_tokens,
                requested_output_tokens=_requested_output_tokens(provider_payload.extra_body),
                limit_types=REQUEST_LIMIT_TYPES,
                gateway_request_id=gateway_request_id,
                gateway_endpoint="chat_completions",
                db=db,
            )
        )
        upstream_extra_body = _normalize_provider_extra_body(
            extra_body=provider_payload.extra_body,
            provider_model=resolved.provider_model,
        )
        upstream_payload = ProviderChatCompletionRequest(
            model=resolved.provider_model,
            messages=provider_payload.messages,
            extra_body=upstream_extra_body,
        )
        if is_streaming:
            if resolved.fallback_disabled_reason is not None:
                await _record_proxy_activity(
                    resolved=resolved,
                    action="proxy.streaming_fallback_disabled",
                    message="Streaming fallback is disabled for this phase.",
                    severity="info",
                    metadata={"reason": resolved.fallback_disabled_reason},
                    gateway_request_id=gateway_request_id,
                    db=db,
                )
            if await guardrails_facade.has_enforced_response_guardrails(
                context=guardrail_context,
                db=db,
            ):
                await _release_reservations(reservation_ids=reservation_ids, db=db)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="streaming is disabled when enforced output guardrails apply",
                )
            upstream_stream = await providers_facade.stream_chat_completion(
                provider_id=resolved.provider_id,
                pool_id=resolved.pool_id,
                provider_credential_id=resolved.provider_key_id,
                payload=upstream_payload,
                scope=Scope(org_id=resolved.org_id),
                db=db,
                http_client=http_client,
            )
            return StreamingResponse(
                _stream_proxy_response(
                    upstream=upstream_stream,
                    resolved=resolved,
                    provider_payload=provider_payload,
                    guardrail_context=guardrail_context,
                    estimated_tokens=estimated_tokens,
                    reservation_ids=reservation_ids,
                    started_at=started_at,
                    db=db,
                ),
                status_code=upstream_stream.status_code,
                media_type=upstream_stream.media_type,
            )

        upstream = await providers_facade.create_chat_completion(
            provider_id=resolved.provider_id,
            pool_id=resolved.pool_id,
            provider_credential_id=resolved.provider_key_id,
            payload=upstream_payload,
            scope=Scope(org_id=resolved.org_id),
            db=db,
            http_client=http_client,
        )
    except InvalidVirtualKeyError as exc:
        await _finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=None,
            http_status=status.HTTP_401_UNAUTHORIZED,
            attempt_count=0,
            fallback_attempted=False,
            error_code="invalid_virtual_key",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ProxyLimitExceededError as exc:
        # A limit policy denied: release any reservations taken earlier in the
        # pipeline (e.g. token/budget reservations from the first enforcement phase)
        # so a request-count denial does not leak them until expiry.
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
        ) from exc
    except AccessDeniedError as exc:
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        if resolved is not None:
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.denied",
                message="Proxy request denied by access, limit, or provider routing policy.",
                severity="warning",
                metadata={"reason": "access_denied"},
                gateway_request_id=gateway_request_id,
                db=db,
            )
        else:
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=None,
                http_status=status.HTTP_403_FORBIDDEN,
                attempt_count=0,
                fallback_attempted=False,
                error_code="access_denied",
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except GuardrailDeniedError as exc:
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                http_status=status.HTTP_403_FORBIDDEN,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="guardrail_denied",
                db=db,
            )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.guardrail_denied",
                message=exc.detail,
                severity="warning",
                metadata={
                    "reason": "guardrail_denied",
                    "policy_id": str(exc.policy_id) if exc.policy_id else None,
                    "rule_id": str(exc.rule_id) if exc.rule_id else None,
                },
                gateway_request_id=gateway_request_id,
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.detail,
        ) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError, ProviderNotFoundError) as exc:
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                http_status=status.HTTP_502_BAD_GATEWAY,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_unavailable",
                db=db,
            )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.provider_unavailable",
                message="Proxy request failed because the provider is unavailable.",
                severity="error",
                metadata={"reason": "provider_unavailable"},
                gateway_request_id=gateway_request_id,
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider is not available",
        ) from exc
    except ProviderUpstreamError as exc:
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                http_status=exc.status_code,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_upstream_error",
                attempt_failure_reason=exc.failure_reason,
                gateway_endpoint="chat_completions",
                db=db,
            )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.provider_error",
                message="Proxy request failed with an upstream provider error.",
                severity="error",
                metadata={"status_code": exc.status_code},
                gateway_request_id=gateway_request_id,
                db=db,
            )
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    try:
        await _evaluate_guardrail_response(
            context=_guardrail_context(
                resolved=resolved,
                provider_payload=provider_payload,
                gateway_request_id=gateway_request_id,
                gateway_endpoint="chat_completions",
            ),
            resolved=resolved,
            response_text=_response_text(upstream.body),
            db=db,
        )
    except GuardrailDeniedError as exc:
        actual_cost_cents = await _record_proxy_request(
            resolved=resolved,
            gateway_request_id=gateway_request_id,
            http_status=status.HTTP_403_FORBIDDEN,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code="guardrail_output_denied",
            provider_credential_id=upstream.provider_credential_id,
            db=db,
        )
        await _commit_reservations(
            reservation_ids=reservation_ids,
            usage=usage,
            cost_cents=actual_cost_cents,
            db=db,
        )
        await _record_proxy_activity(
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc

    actual_cost_cents = await _record_proxy_request(
        resolved=resolved,
        http_status=upstream.status_code,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        error_code=None,
        provider_credential_id=upstream.provider_credential_id,
        db=db,
    )
    await _commit_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=actual_cost_cents,
        db=db,
    )
    return JSONResponse(status_code=upstream.status_code, content=upstream.body)


@router.post("/messages", response_model=None)
async def create_anthropic_message(
    request: Request,
    db: DatabaseSession,
    http_client: ProxyHttpClient,
    authorization: VirtualKeyAuthorization = None,
    anthropic_api_key: AnthropicApiKey = None,
    provider_id: ProviderIdHeader = None,
    anthropic_version: Annotated[str, Header(alias="anthropic-version")] = "2023-06-01",
) -> Response:
    started_at = perf_counter()
    raw_body = await _read_body_within_limit(request, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    if body.get("stream") is True:
        raise HTTPException(status_code=400, detail="native Anthropic streaming is not supported")

    provider_payload = _to_anthropic_payload(body)
    raw_key = _extract_anthropic_virtual_key(
        authorization=authorization,
        api_key=anthropic_api_key,
    )
    resolved = None
    plan: ResolvedAccessPlan | None = None
    gateway_request_id: UUID | None = None
    attempted_routes = 0
    fallback_attempted = False
    reservation_ids: list[UUID] = []
    guardrail_context: GuardrailEvaluationContext | None = None
    selected_attempt_index = 0
    current_route_attempt_id: UUID | None = None
    final_route_attempt_id: UUID | None = None
    try:
        gateway_request_id = await _create_gateway_request(
            resolved=None,
            requested_model=provider_payload.model,
            gateway_endpoint="anthropic_messages",
            db=db,
        )
        plan = await keys_facade.resolve_access_plan(
            payload=ResolveAccessRequest(
                raw_key=raw_key,
                requested_model=provider_payload.model,
                provider_id=provider_id,
                gateway_endpoint="anthropic_messages",
            ),
            db=db,
        )
        resolved = _resolved_access_from_attempt(plan=plan, attempt_index=0)
        org_settings = await settings_facade.get_organization_settings(
            scope=Scope(org_id=resolved.org_id),
            db=db,
        )
        _enforce_body_size(raw_body, org_settings.default_max_body_bytes)
        await _record_gateway_access_decision(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
        estimated_tokens = estimate_request_tokens(provider_payload.messages)
        guardrail_payload = ProviderChatCompletionRequest(
            model=provider_payload.model,
            messages=provider_payload.messages,
            extra_body=provider_payload.extra_body,
        )
        last_upstream_error: ProviderUpstreamError | None = None
        for attempt_index, _attempt in enumerate(plan.attempts):
            resolved = _resolved_access_from_attempt(plan=plan, attempt_index=attempt_index)
            selected_attempt_index = attempt_index
            attempted_routes = max(attempted_routes, attempt_index + 1)
            reservation_ids = []
            current_route_attempt_id = await _record_gateway_route_attempt_started(
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
                _enforce_provider_body_size(raw_body, resolved_provider.max_body_bytes)
                guardrail_context = _guardrail_context(
                    resolved=resolved,
                    provider_payload=guardrail_payload,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=current_route_attempt_id,
                    gateway_endpoint="anthropic_messages",
                )
                await _evaluate_guardrail_request(
                    context=guardrail_context,
                    resolved=resolved,
                    db=db,
                )
                reservation_ids = await _enforce_limit_policies(
                    resolved=resolved,
                    estimated_input_tokens=estimated_tokens,
                    requested_output_tokens=_requested_output_tokens(provider_payload.extra_body),
                    limit_types=ESTIMATED_LIMIT_TYPES,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=current_route_attempt_id,
                    gateway_endpoint="anthropic_messages",
                    db=db,
                )
                reservation_ids.extend(
                    await _enforce_limit_policies(
                        resolved=resolved,
                        estimated_input_tokens=estimated_tokens,
                        requested_output_tokens=_requested_output_tokens(
                            provider_payload.extra_body
                        ),
                        limit_types=REQUEST_LIMIT_TYPES,
                        gateway_request_id=gateway_request_id,
                        route_attempt_id=current_route_attempt_id,
                        gateway_endpoint="anthropic_messages",
                        db=db,
                    )
                )
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
                final_route_attempt_id = current_route_attempt_id
                break
            except ProviderUpstreamError as exc:
                last_upstream_error = exc
                await _finalize_gateway_route_attempt(
                    route_attempt_id=current_route_attempt_id,
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
                if not _should_try_next_route(
                    plan=plan,
                    attempt_index=attempt_index,
                    failure_reason=exc.failure_reason,
                ):
                    raise
                fallback_attempted = True
                await _record_proxy_request(
                    resolved=resolved,
                    gateway_request_id=gateway_request_id,
                    http_status=exc.status_code,
                    latency_ms=_elapsed_ms(started_at),
                    usage=unknown_usage(),
                    error_code="provider_upstream_error",
                    routing_attempt_index=attempt_index,
                    is_final_attempt=False,
                    attempt_failure_reason=exc.failure_reason,
                    gateway_endpoint="anthropic_messages",
                    db=db,
                )
                await _release_reservations(reservation_ids=reservation_ids, db=db)
                await _record_proxy_activity(
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
        else:
            assert last_upstream_error is not None
            raise last_upstream_error
    except InvalidVirtualKeyError as exc:
        await _finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=None,
            http_status=status.HTTP_401_UNAUTHORIZED,
            attempt_count=0,
            fallback_attempted=False,
            error_code="invalid_virtual_key",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ProxyLimitExceededError as exc:
        # A limit policy denied: release any reservations taken earlier in the
        # pipeline (e.g. token/budget reservations from the first enforcement phase)
        # so a request-count denial does not leak them until expiry.
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        await _finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            http_status=status.HTTP_429_TOO_MANY_REQUESTS,
            attempt_count=attempted_routes or 1,
            fallback_attempted=fallback_attempted,
            error_code="limit_exceeded",
            db=db,
            final_route_attempt_id=final_route_attempt_id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
        ) from exc
    except AccessDeniedError as exc:
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                http_status=status.HTTP_403_FORBIDDEN,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="access_denied",
                db=db,
            )
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=resolved,
                http_status=status.HTTP_403_FORBIDDEN,
                attempt_count=attempted_routes or 1,
                fallback_attempted=fallback_attempted,
                error_code="access_denied",
                db=db,
            )
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.denied",
                message="Native Anthropic request denied by access or provider routing policy.",
                severity="warning",
                metadata={"reason": "access_denied"},
                gateway_request_id=gateway_request_id,
                db=db,
            )
        else:
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=None,
                http_status=status.HTTP_403_FORBIDDEN,
                attempt_count=0,
                fallback_attempted=False,
                error_code="access_denied",
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except GuardrailDeniedError as exc:
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                http_status=status.HTTP_403_FORBIDDEN,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="guardrail_denied",
                db=db,
            )
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=resolved,
                http_status=status.HTTP_403_FORBIDDEN,
                attempt_count=attempted_routes or 1,
                fallback_attempted=fallback_attempted,
                error_code="guardrail_denied",
                db=db,
                final_route_attempt_id=final_route_attempt_id,
            )
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.guardrail_denied",
                message=exc.detail,
                severity="warning",
                metadata={
                    "reason": "guardrail_denied",
                    "policy_id": str(exc.policy_id) if exc.policy_id else None,
                    "rule_id": str(exc.rule_id) if exc.rule_id else None,
                },
                gateway_request_id=gateway_request_id,
                db=db,
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError, ProviderNotFoundError) as exc:
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                http_status=status.HTTP_502_BAD_GATEWAY,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_unavailable",
                db=db,
            )
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=resolved,
                http_status=status.HTTP_502_BAD_GATEWAY,
                attempt_count=attempted_routes or 1,
                fallback_attempted=fallback_attempted,
                error_code="provider_unavailable",
                db=db,
                final_route_attempt_id=final_route_attempt_id,
            )
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.provider_unavailable",
                message="Native Anthropic provider is not available.",
                severity="error",
                metadata={"reason": "provider_unavailable"},
                gateway_request_id=gateway_request_id,
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider is not available",
        ) from exc
    except ProviderUpstreamError as exc:
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                http_status=exc.status_code,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_upstream_error",
                routing_attempt_index=selected_attempt_index,
                attempt_failure_reason=exc.failure_reason,
                gateway_endpoint="anthropic_messages",
                db=db,
            )
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=resolved,
                http_status=exc.status_code,
                attempt_count=attempted_routes or 1,
                fallback_attempted=fallback_attempted,
                error_code="provider_upstream_error",
                db=db,
                final_route_attempt_id=final_route_attempt_id or current_route_attempt_id,
            )
            if fallback_attempted:
                await _record_proxy_activity(
                    resolved=resolved,
                    action="proxy.routing_fallback_exhausted",
                    message="Native Anthropic fallback candidates were exhausted.",
                    severity="error",
                    metadata={
                        "reason": exc.failure_reason,
                        "http_status": exc.status_code,
                    },
                    gateway_request_id=gateway_request_id,
                    db=db,
                )
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.upstream_failed",
                message="Native Anthropic provider request failed.",
                severity="error",
                metadata={
                    "reason": "provider_upstream_error",
                    "http_status": exc.status_code,
                },
                gateway_request_id=gateway_request_id,
                db=db,
            )
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    try:
        await _evaluate_guardrail_response(
            context=guardrail_context
            or _guardrail_context(
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
    except GuardrailDeniedError as exc:
        actual_cost_cents = await _record_proxy_request(
            resolved=resolved,
            http_status=status.HTTP_403_FORBIDDEN,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code="guardrail_output_denied",
            provider_credential_id=upstream.provider_credential_id,
            routing_attempt_index=selected_attempt_index,
            gateway_endpoint="anthropic_messages",
            db=db,
        )
        await _finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            http_status=status.HTTP_403_FORBIDDEN,
            attempt_count=attempted_routes or 1,
            fallback_attempted=fallback_attempted,
            error_code="guardrail_output_denied",
            db=db,
            final_route_attempt_id=final_route_attempt_id,
        )
        await _commit_reservations(
            reservation_ids=reservation_ids,
            usage=usage,
            cost_cents=actual_cost_cents,
            db=db,
        )
        await _record_proxy_activity(
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    actual_cost_cents = await _record_proxy_request(
        resolved=resolved,
        gateway_request_id=gateway_request_id,
        http_status=upstream.status_code,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        error_code=None,
        provider_credential_id=upstream.provider_credential_id,
        routing_attempt_index=selected_attempt_index,
        gateway_endpoint="anthropic_messages",
        db=db,
    )
    await _finalize_gateway_route_attempt(
        route_attempt_id=final_route_attempt_id,
        status_="succeeded",
        http_status=upstream.status_code,
        error_code=None,
        failure_reason=None,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        cost_cents=actual_cost_cents,
        cost_micro_cents=_calculate_cost_micro_cents(resolved=resolved, usage=usage),
        usage_source=usage.usage_source,
        db=db,
    )
    await _finalize_gateway_request(
        gateway_request_id=gateway_request_id,
        resolved=resolved,
        http_status=upstream.status_code,
        attempt_count=attempted_routes or 1,
        fallback_attempted=fallback_attempted,
        error_code=None,
        db=db,
        final_route_attempt_id=final_route_attempt_id,
    )
    if fallback_attempted:
        await _record_proxy_activity(
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
    await _commit_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=actual_cost_cents,
        db=db,
    )
    return JSONResponse(status_code=upstream.status_code, content=upstream.body)


@router.post("/embeddings", response_model=None)
async def create_embeddings() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error": {
                "message": "Embeddings are not implemented yet.",
                "type": "not_implemented",
                "code": "embeddings_not_implemented",
            }
        },
    )


async def _execute_chat_proxy(
    *,
    body: dict[str, Any],
    raw_body: bytes,
    started_at: float,
    gateway_endpoint: str,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    authorization: str | None,
    provider_id: UUID | None,
    response_transform,
) -> Response:
    provider_payload = _to_provider_payload(body)
    raw_key = _extract_bearer_token(authorization)
    resolved = None
    plan: ResolvedAccessPlan | None = None
    gateway_request_id: UUID | None = None
    attempted_routes = 0
    fallback_attempted = False
    reservation_ids: list[UUID] = []
    selected_attempt_index = 0
    current_route_attempt_id: UUID | None = None
    final_route_attempt_id: UUID | None = None
    try:
        gateway_request_id = await _create_gateway_request(
            resolved=None,
            requested_model=provider_payload.model,
            gateway_endpoint=gateway_endpoint,
            db=db,
        )
        plan = await keys_facade.resolve_access_plan(
            payload=ResolveAccessRequest(
                raw_key=raw_key,
                requested_model=provider_payload.model,
                provider_id=provider_id,
                gateway_endpoint=gateway_endpoint,
            ),
            db=db,
        )
        resolved = _resolved_access_from_attempt(plan=plan, attempt_index=0)
        org_settings = await settings_facade.get_organization_settings(
            scope=Scope(org_id=resolved.org_id),
            db=db,
        )
        _enforce_body_size(raw_body, org_settings.default_max_body_bytes)
        await _record_gateway_access_decision(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
        estimated_tokens = estimate_request_tokens(provider_payload.messages)
        last_upstream_error: ProviderUpstreamError | None = None
        for attempt_index, _attempt in enumerate(plan.attempts):
            resolved = _resolved_access_from_attempt(plan=plan, attempt_index=attempt_index)
            selected_attempt_index = attempt_index
            attempted_routes = max(attempted_routes, attempt_index + 1)
            reservation_ids = []
            current_route_attempt_id = await _record_gateway_route_attempt_started(
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
                _enforce_provider_body_size(raw_body, resolved_provider.max_body_bytes)
                await _evaluate_guardrail_request(
                    context=_guardrail_context(
                        resolved=resolved,
                        provider_payload=provider_payload,
                        gateway_request_id=gateway_request_id,
                        route_attempt_id=current_route_attempt_id,
                        gateway_endpoint=gateway_endpoint,
                    ),
                    resolved=resolved,
                    db=db,
                )
                reservation_ids = await _enforce_limit_policies(
                    resolved=resolved,
                    estimated_input_tokens=estimated_tokens,
                    requested_output_tokens=_requested_output_tokens(provider_payload.extra_body),
                    limit_types=ESTIMATED_LIMIT_TYPES,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=current_route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    db=db,
                )
                reservation_ids.extend(
                    await _enforce_limit_policies(
                        resolved=resolved,
                        estimated_input_tokens=estimated_tokens,
                        requested_output_tokens=_requested_output_tokens(
                            provider_payload.extra_body
                        ),
                        limit_types=REQUEST_LIMIT_TYPES,
                        gateway_request_id=gateway_request_id,
                        route_attempt_id=current_route_attempt_id,
                        gateway_endpoint=gateway_endpoint,
                        db=db,
                    )
                )
                upstream_extra_body = _normalize_provider_extra_body(
                    extra_body=provider_payload.extra_body,
                    provider_model=resolved.provider_model,
                )
                upstream = await providers_facade.create_chat_completion(
                    provider_id=resolved.provider_id,
                    pool_id=resolved.pool_id,
                    provider_credential_id=resolved.provider_key_id,
                    payload=ProviderChatCompletionRequest(
                        model=resolved.provider_model,
                        messages=provider_payload.messages,
                        extra_body=upstream_extra_body,
                    ),
                    scope=Scope(org_id=resolved.org_id),
                    db=db,
                    http_client=http_client,
                )
                selected_attempt_index = attempt_index
                final_route_attempt_id = current_route_attempt_id
                break
            except ProviderUpstreamError as exc:
                last_upstream_error = exc
                await _finalize_gateway_route_attempt(
                    route_attempt_id=current_route_attempt_id,
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
                if not _should_try_next_route(
                    plan=plan,
                    attempt_index=attempt_index,
                    failure_reason=exc.failure_reason,
                ):
                    raise
                fallback_attempted = True
                await _record_proxy_request(
                    resolved=resolved,
                    gateway_request_id=gateway_request_id,
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
                await _release_reservations(reservation_ids=reservation_ids, db=db)
                await _record_proxy_activity(
                    resolved=resolved,
                    action="proxy.routing_fallback_attempted",
                    message="Provider request failed; trying the next route candidate.",
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
        else:
            assert last_upstream_error is not None
            raise last_upstream_error
    except InvalidVirtualKeyError as exc:
        await _finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=None,
            http_status=status.HTTP_401_UNAUTHORIZED,
            attempt_count=0,
            fallback_attempted=False,
            error_code="invalid_virtual_key",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ProxyLimitExceededError as exc:
        # A limit policy denied: release any reservations taken earlier in the
        # pipeline (e.g. token/budget reservations from the first enforcement phase)
        # so a request-count denial does not leak them until expiry.
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        await _finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            http_status=status.HTTP_429_TOO_MANY_REQUESTS,
            attempt_count=attempted_routes or 1,
            fallback_attempted=fallback_attempted,
            error_code="limit_exceeded",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
        ) from exc
    except AccessDeniedError as exc:
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        if resolved is not None:
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.denied",
                message="Proxy request denied by access, limit, or provider routing policy.",
                severity="warning",
                metadata={"reason": "access_denied"},
                gateway_request_id=gateway_request_id,
                db=db,
            )
        else:
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=None,
                http_status=status.HTTP_403_FORBIDDEN,
                attempt_count=0,
                fallback_attempted=False,
                error_code="access_denied",
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except GuardrailDeniedError as exc:
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                http_status=status.HTTP_403_FORBIDDEN,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="guardrail_denied",
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=resolved,
                http_status=status.HTTP_403_FORBIDDEN,
                attempt_count=attempted_routes or 1,
                fallback_attempted=fallback_attempted,
                error_code="guardrail_denied",
                db=db,
            )
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.guardrail_denied",
                message=exc.detail,
                severity="warning",
                metadata={
                    "reason": "guardrail_denied",
                    "policy_id": str(exc.policy_id) if exc.policy_id else None,
                    "rule_id": str(exc.rule_id) if exc.rule_id else None,
                },
                gateway_request_id=gateway_request_id,
                db=db,
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError, ProviderNotFoundError) as exc:
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                http_status=status.HTTP_502_BAD_GATEWAY,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_unavailable",
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=resolved,
                http_status=status.HTTP_502_BAD_GATEWAY,
                attempt_count=attempted_routes or 1,
                fallback_attempted=fallback_attempted,
                error_code="provider_unavailable",
                db=db,
            )
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.provider_unavailable",
                message="Provider is not available.",
                severity="error",
                metadata={"reason": "provider_unavailable"},
                gateway_request_id=gateway_request_id,
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider is not available",
        ) from exc
    except ProviderUpstreamError as exc:
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                http_status=exc.status_code,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="provider_upstream_error",
                routing_attempt_index=selected_attempt_index,
                attempt_failure_reason=exc.failure_reason,
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
            await _finalize_gateway_request(
                gateway_request_id=gateway_request_id,
                resolved=resolved,
                http_status=exc.status_code,
                attempt_count=attempted_routes or 1,
                fallback_attempted=fallback_attempted,
                error_code="provider_upstream_error",
                db=db,
                final_route_attempt_id=final_route_attempt_id or current_route_attempt_id,
            )
            if fallback_attempted:
                await _record_proxy_activity(
                    resolved=resolved,
                    action="proxy.routing_fallback_exhausted",
                    message="Fallback candidates were exhausted.",
                    severity="error",
                    metadata={
                        "reason": exc.failure_reason,
                        "http_status": exc.status_code,
                    },
                    gateway_request_id=gateway_request_id,
                    db=db,
                )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.upstream_failed",
                message="Provider request failed.",
                severity="error",
                metadata={
                    "reason": "provider_upstream_error",
                    "http_status": exc.status_code,
                },
                gateway_request_id=gateway_request_id,
                db=db,
            )
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    try:
        await _evaluate_guardrail_response(
            context=_guardrail_context(
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
    except GuardrailDeniedError as exc:
        actual_cost_cents = await _record_proxy_request(
            resolved=resolved,
            gateway_request_id=gateway_request_id,
            http_status=status.HTTP_403_FORBIDDEN,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code="guardrail_output_denied",
            provider_credential_id=upstream.provider_credential_id,
            routing_attempt_index=selected_attempt_index,
            gateway_endpoint=gateway_endpoint,
            db=db,
        )
        await _finalize_gateway_route_attempt(
            route_attempt_id=final_route_attempt_id,
            status_="blocked",
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="guardrail_output_denied",
            failure_reason=None,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            cost_cents=actual_cost_cents,
            cost_micro_cents=_calculate_cost_micro_cents(resolved=resolved, usage=usage),
            usage_source=usage.usage_source,
            db=db,
        )
        await _finalize_gateway_request(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            http_status=status.HTTP_403_FORBIDDEN,
            attempt_count=attempted_routes or 1,
            fallback_attempted=fallback_attempted,
            error_code="guardrail_output_denied",
            db=db,
            final_route_attempt_id=final_route_attempt_id,
        )
        await _commit_reservations(
            reservation_ids=reservation_ids,
            usage=usage,
            cost_cents=actual_cost_cents,
            db=db,
        )
        await _record_proxy_activity(
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    actual_cost_cents = await _record_proxy_request(
        resolved=resolved,
        gateway_request_id=gateway_request_id,
        http_status=upstream.status_code,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        error_code=None,
        provider_credential_id=upstream.provider_credential_id,
        routing_attempt_index=selected_attempt_index,
        gateway_endpoint=gateway_endpoint,
        db=db,
    )
    await _finalize_gateway_route_attempt(
        route_attempt_id=final_route_attempt_id,
        status_="succeeded",
        http_status=upstream.status_code,
        error_code=None,
        failure_reason=None,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        cost_cents=actual_cost_cents,
        cost_micro_cents=_calculate_cost_micro_cents(resolved=resolved, usage=usage),
        usage_source=usage.usage_source,
        db=db,
    )
    await _finalize_gateway_request(
        gateway_request_id=gateway_request_id,
        resolved=resolved,
        http_status=upstream.status_code,
        attempt_count=attempted_routes or 1,
        fallback_attempted=fallback_attempted,
        error_code=None,
        db=db,
        final_route_attempt_id=final_route_attempt_id,
    )
    if fallback_attempted:
        await _record_proxy_activity(
            resolved=resolved,
            action="proxy.routing_fallback_succeeded",
            message="Provider request succeeded after fallback.",
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
    await _commit_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=actual_cost_cents,
        db=db,
    )
    return JSONResponse(status_code=upstream.status_code, content=response_transform(upstream.body))


async def _stream_proxy_response(
    *,
    upstream,
    resolved,
    provider_payload: ProviderChatCompletionRequest,
    guardrail_context: GuardrailEvaluationContext,
    estimated_tokens: int,
    reservation_ids: list[UUID],
    started_at: float,
    db: AsyncSession,
):
    chunks: list[bytes] = []
    error_code: str | None = None
    try:
        async for chunk in upstream.chunks:
            chunks.append(chunk)
            yield chunk
    except Exception:
        error_code = "provider_stream_error"
        raise
    finally:
        await upstream.close()
        if error_code is None:
            try:
                await _evaluate_guardrail_response(
                    context=guardrail_context,
                    resolved=resolved,
                    response_text=_stream_response_text(chunks),
                    db=db,
                )
            except GuardrailDeniedError as exc:
                await _record_proxy_activity(
                    resolved=resolved,
                    action="proxy.guardrail_output_denied",
                    message=exc.detail,
                    severity="warning",
                    metadata={
                        "reason": "guardrail_output_denied",
                        "policy_id": str(exc.policy_id) if exc.policy_id else None,
                        "rule_id": str(exc.rule_id) if exc.rule_id else None,
                        "streaming": True,
                    },
                    gateway_request_id=guardrail_context.gateway_request_id,
                    db=db,
                )
        usage = usage_from_stream_chunks(
            request_messages=provider_payload.messages,
            chunks=chunks,
        )
        usage_cost_cents = await _record_proxy_request(
            resolved=resolved,
            gateway_request_id=guardrail_context.gateway_request_id,
            http_status=upstream.status_code,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code=error_code,
            provider_credential_id=upstream.provider_credential_id,
            db=db,
        )
        if error_code is None:
            await _commit_reservations(
                reservation_ids=reservation_ids,
                usage=usage,
                cost_cents=usage_cost_cents,
                db=db,
            )
        else:
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.stream_failed",
                message="Provider stream failed after the response started.",
                severity="error",
                metadata={"reason": error_code},
                gateway_request_id=guardrail_context.gateway_request_id,
                db=db,
            )


async def _read_body_within_limit(request: Request, max_body_bytes: int) -> bytes:
    # Cheap reject when the client honestly declares an oversized body.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content-length header") from exc
        if declared > max_body_bytes:
            raise HTTPException(status_code=413, detail="request body is too large")
    # Stream with a running byte counter so a chunked or under-declared body is
    # aborted before the whole payload is buffered into memory. This runs before
    # virtual-key authentication, so it is the guard against unauthenticated OOM.
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_body_bytes:
            raise HTTPException(status_code=413, detail="request body is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _enforce_body_size(raw_body: bytes, max_body_bytes: int) -> None:
    if len(raw_body) > max_body_bytes:
        raise HTTPException(status_code=413, detail="request body is too large")


def _enforce_provider_body_size(raw_body: bytes, max_body_bytes: int | None) -> None:
    if max_body_bytes is not None and len(raw_body) > max_body_bytes:
        raise HTTPException(status_code=413, detail="request body exceeds provider limit")


def _decode_json_body(raw_body: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


def _to_provider_payload(body: dict[str, Any]) -> ProviderChatCompletionRequest:
    extra_body = dict(body)
    model = extra_body.pop("model", None)
    messages = extra_body.pop("messages", None)
    try:
        return ProviderChatCompletionRequest(
            model=model,
            messages=messages,
            extra_body=extra_body,
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _to_anthropic_payload(body: dict[str, Any]) -> ProviderAnthropicMessagesRequest:
    extra_body = dict(body)
    model = extra_body.pop("model", None)
    messages = extra_body.pop("messages", None)
    try:
        return ProviderAnthropicMessagesRequest(
            model=model,
            messages=messages,
            extra_body=extra_body,
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _messages_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        parts.append(_content_to_text(message.get("content")))
    return "\n".join(parts)


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


def _guardrail_context(
    *,
    resolved,
    provider_payload: ProviderChatCompletionRequest,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
    gateway_endpoint: str | None = None,
) -> GuardrailEvaluationContext:
    return GuardrailEvaluationContext(
        org_id=resolved.org_id,
        team_id=resolved.team_id,
        project_id=resolved.project_id,
        virtual_key_id=resolved.virtual_key_id,
        provider_id=resolved.provider_id,
        pool_id=resolved.pool_id,
        provider_model_offering_id=resolved.model_offering_id,
        public_model_id=resolved.public_model_id,
        public_model_name=resolved.public_model_name,
        route_candidate_id=resolved.route_candidate_id,
        gateway_endpoint=gateway_endpoint,
        request_id=current_request_id(),
        gateway_request_id=gateway_request_id,
        route_attempt_id=route_attempt_id,
        requested_model=resolved.requested_model,
        provider_model=resolved.provider_model,
        prompt_text=_messages_text(provider_payload.messages),
    )


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


def _completion_body_to_chat_body(body: dict[str, Any]) -> dict[str, Any]:
    prompt = body.get("prompt")
    if isinstance(prompt, list):
        content = "\n".join(str(item) for item in prompt)
    elif prompt is None:
        raise HTTPException(status_code=400, detail="prompt is required")
    else:
        content = str(prompt)
    extra_body = {
        key: value
        for key, value in body.items()
        if key not in {"prompt", "suffix", "echo", "best_of"}
    }
    return {
        **extra_body,
        "messages": [{"role": "user", "content": content}],
    }


def _responses_body_to_chat_body(body: dict[str, Any]) -> dict[str, Any]:
    input_value = body.get("input")
    if input_value is None:
        raise HTTPException(status_code=400, detail="input is required")
    if isinstance(input_value, str):
        messages = [{"role": "user", "content": input_value}]
    elif isinstance(input_value, list):
        messages = input_value
    else:
        messages = [{"role": "user", "content": str(input_value)}]
    extra_body = {
        key: value
        for key, value in body.items()
        if key not in {"input", "instructions", "text", "reasoning"}
    }
    if isinstance(body.get("instructions"), str):
        messages = [{"role": "system", "content": body["instructions"]}, *messages]
    if "max_output_tokens" in extra_body and "max_completion_tokens" not in extra_body:
        extra_body["max_completion_tokens"] = extra_body.pop("max_output_tokens")
    return {
        **extra_body,
        "messages": messages,
    }


def _chat_response_to_completion(
    response_body: dict[str, Any],
    request_body: dict[str, Any],
) -> dict[str, Any]:
    choices = response_body.get("choices") if isinstance(response_body, dict) else None
    completion_choices = []
    if isinstance(choices, list):
        for index, choice in enumerate(choices):
            message = choice.get("message") if isinstance(choice, dict) else None
            text = message.get("content") if isinstance(message, dict) else None
            completion_choices.append(
                {
                    "text": text or "",
                    "index": choice.get("index", index) if isinstance(choice, dict) else index,
                    "logprobs": None,
                    "finish_reason": choice.get("finish_reason")
                    if isinstance(choice, dict)
                    else None,
                }
            )
    return {
        "id": response_body.get("id", "cmpl-bab")
        if isinstance(response_body, dict)
        else "cmpl-bab",
        "object": "text_completion",
        "created": response_body.get("created") if isinstance(response_body, dict) else None,
        "model": request_body.get("model"),
        "choices": completion_choices,
        "usage": response_body.get("usage") if isinstance(response_body, dict) else None,
    }


def _chat_response_to_response(
    response_body: dict[str, Any],
    request_body: dict[str, Any],
) -> dict[str, Any]:
    choices = response_body.get("choices") if isinstance(response_body, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    message = first_choice.get("message") if isinstance(first_choice, dict) else {}
    text = message.get("content") if isinstance(message, dict) else ""
    return {
        "id": response_body.get("id", "resp_bab")
        if isinstance(response_body, dict)
        else "resp_bab",
        "object": "response",
        "created_at": response_body.get("created") if isinstance(response_body, dict) else None,
        "model": request_body.get("model"),
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text or ""}],
            }
        ],
        "output_text": text or "",
        "usage": response_body.get("usage") if isinstance(response_body, dict) else None,
    }


def _normalize_provider_extra_body(
    *,
    extra_body: dict[str, Any],
    provider_model: str,
) -> dict[str, Any]:
    normalized = dict(extra_body)
    if (
        _uses_completion_token_limit(provider_model)
        and "max_tokens" in normalized
        and "max_completion_tokens" not in normalized
    ):
        normalized["max_completion_tokens"] = normalized.pop("max_tokens")
    return normalized


def _uses_completion_token_limit(provider_model: str) -> bool:
    normalized_model = provider_model.lower()
    return normalized_model.startswith(("gpt-5", "o1", "o3", "o4"))


def _should_try_next_route(
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


def _resolved_access_from_attempt(
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


def _extract_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def _extract_anthropic_virtual_key(*, authorization: str | None, api_key: str | None) -> str:
    bearer_key = _extract_bearer_token(authorization) if authorization is not None else None
    header_key = api_key.strip() if api_key else None
    if bearer_key and header_key and bearer_key != header_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="conflicting virtual key headers",
        )
    key = header_key or bearer_key
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing virtual key")
    return key


async def _record_proxy_request(
    *,
    resolved: ResolvedAccess,
    gateway_request_id: UUID | None = None,
    http_status: int,
    latency_ms: int,
    usage: UsageAccounting,
    error_code: str | None,
    db: AsyncSession,
    provider_credential_id: UUID | None = None,
    routing_attempt_index: int = 0,
    is_final_attempt: bool = True,
    fallback_from_candidate_id: UUID | None = None,
    fallback_trigger_reason: str | None = None,
    attempt_failure_reason: str | None = None,
    gateway_endpoint: str | None = None,
) -> int | None:
    cost_cents = _calculate_cost_cents(resolved=resolved, usage=usage)
    cost_micro_cents = _calculate_cost_micro_cents(resolved=resolved, usage=usage)
    dimension_subject = _limit_dimension_subject(
        resolved=resolved,
        gateway_endpoint=gateway_endpoint,
    )
    dimension_snapshot = to_dimension_snapshot(
        dimension_subject,
        stage=PolicyDimensionStage.LIMIT_COMMIT,
    )
    limit_counter_key = await _usage_limit_counter_key(
        resolved=resolved,
        subject=dimension_subject,
        db=db,
    )
    limit_counting_unit = await _usage_limit_counting_unit(resolved=resolved, db=db)
    limit_window_descriptor = await _usage_limit_window_descriptor(resolved=resolved)
    usage_record_id = await usage_facade.create_usage_record(
        payload=RecordUsage(
            org_id=resolved.org_id,
            team_id=resolved.team_id,
            project_id=resolved.project_id,
            access_policy_id=resolved.access_policy_id,
            access_policy_route_id=resolved.access_policy_route_id,
            gateway_request_id=gateway_request_id,
            public_model_id=resolved.public_model_id,
            route_candidate_id=resolved.route_candidate_id,
            limit_policy_ids=[str(limit_id) for limit_id in resolved.limit_policy_ids],
            limit_policy_rule_ids=[
                str(limit.limit_policy_rule_id) for limit in resolved.limit_policies
            ],
            limit_policy_assignment_ids=[
                str(limit.limit_policy_assignment_id) for limit in resolved.limit_policies
            ],
            limit_counter_key=limit_counter_key,
            limit_counting_unit=limit_counting_unit,
            limit_window_descriptor=limit_window_descriptor,
            dimension_snapshot=dimension_snapshot,
            virtual_key_id=resolved.virtual_key_id,
            pool_id=resolved.pool_id,
            provider_id=resolved.provider_id,
            provider_credential_id=provider_credential_id or resolved.provider_key_id,
            request_id=current_request_id(),
            requested_model=resolved.requested_model,
            provider_model=resolved.provider_model,
            public_model_name=resolved.public_model_name,
            routing_mode=resolved.routing_mode,
            routing_attempt_index=routing_attempt_index,
            is_final_attempt=is_final_attempt,
            primary_route_candidate_id=resolved.primary_route_candidate_id,
            fallback_from_candidate_id=fallback_from_candidate_id,
            fallback_trigger_reason=fallback_trigger_reason,
            attempt_failure_reason=attempt_failure_reason,
            gateway_endpoint=gateway_endpoint,
            http_status=http_status,
            latency_ms=latency_ms,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_cents=cost_cents,
            cost_micro_cents=cost_micro_cents,
            usage_source=usage.usage_source,
            error_code=error_code,
        ),
        db=db,
    )
    if http_status < 400:
        for limit in resolved.limit_policies:
            counter_key = await _limit_rule_counter_key(
                limit=limit,
                subject=dimension_subject,
                db=db,
            )
            counting_unit = await _limit_rule_counting_unit(
                org_id=resolved.org_id,
                limit=limit,
                db=db,
            )
            await usage_facade.create_limit_policy_committed_usage(
                payload=RecordLimitPolicyCommittedUsage(
                    org_id=resolved.org_id,
                    usage_record_id=usage_record_id,
                    limit_policy_id=limit.limit_policy_id,
                    limit_policy_revision_id=limit.limit_policy_revision_id,
                    limit_policy_rule_id=limit.limit_policy_rule_id,
                    limit_policy_assignment_id=limit.limit_policy_assignment_id,
                    counter_key=counter_key,
                    counting_unit=counting_unit,
                    window_descriptor=_limit_policy_window_descriptor(limit),
                    dimension_snapshot=dimension_snapshot,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    cost_cents=cost_cents,
                    cost_micro_cents=cost_micro_cents,
                ),
                db=db,
            )
        await db.commit()
    return cost_cents


async def _create_gateway_request(
    *,
    resolved: ResolvedAccess | None,
    requested_model: str | None = None,
    gateway_endpoint: str,
    db: AsyncSession,
) -> UUID | None:
    try:
        return await usage_facade.create_gateway_request(
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
    except Exception:
        await db.rollback()
        return None


async def _finalize_gateway_request(
    *,
    gateway_request_id: UUID | None,
    resolved: ResolvedAccess | None,
    http_status: int,
    attempt_count: int,
    fallback_attempted: bool,
    error_code: str | None,
    db: AsyncSession,
    final_route_attempt_id: UUID | None = None,
) -> None:
    if gateway_request_id is None:
        return
    await usage_facade.finalize_gateway_request(
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


async def _record_gateway_route_attempt_started(
    *,
    gateway_request_id: UUID | None,
    resolved: ResolvedAccess,
    attempt_index: int,
    db: AsyncSession,
) -> UUID | None:
    if gateway_request_id is None:
        return None
    route_attempt_id = await usage_facade.create_gateway_route_attempt(
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
            "credential_pool_id": resolved.pool_id,
            "provider_credential_id": resolved.provider_key_id,
            "provider_model_offering_id": resolved.model_offering_id,
            "provider_model": resolved.provider_model,
            "public_model_name": resolved.public_model_name,
            "status": "started",
            "usage_source": "unknown",
            "pricing_snapshot": {
                "input_price_per_million_tokens": resolved.input_price_per_million_tokens,
                "output_price_per_million_tokens": resolved.output_price_per_million_tokens,
            },
            "capability_snapshot": {},
            "route_snapshot": {
                "routing_mode": resolved.routing_mode,
                "fallback_disabled_reason": resolved.fallback_disabled_reason,
            },
            "started_at": datetime.now(UTC),
        },
        db=db,
    )
    assignment = (
        await policies_repository.get_policy_assignment(
            assignment_id=resolved.access_policy_assignment_id,
            org_id=resolved.org_id,
            db=db,
        )
        if resolved.access_policy_assignment_id is not None
        else None
    )
    await usage_facade.create_gateway_policy_decision(
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
            "metadata_": {"attempt_index": attempt_index},
        },
        db=db,
    )
    return route_attempt_id


async def _finalize_gateway_route_attempt(
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
    await usage_facade.update_gateway_route_attempt(
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


async def _record_gateway_access_decision(
    *,
    gateway_request_id: UUID | None,
    resolved: ResolvedAccess,
    db: AsyncSession,
) -> None:
    if gateway_request_id is None:
        return
    assignment = (
        await policies_repository.get_policy_assignment(
            assignment_id=resolved.access_policy_assignment_id,
            org_id=resolved.org_id,
            db=db,
        )
        if resolved.access_policy_assignment_id is not None
        else None
    )
    await usage_facade.create_gateway_policy_decision(
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


async def _enforce_limit_policies(
    *,
    resolved,
    estimated_input_tokens: int,
    requested_output_tokens: int | None,
    limit_types: set[str] | None = None,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
    gateway_endpoint: str | None = None,
    db: AsyncSession,
) -> list[UUID]:
    requested_total_tokens = estimated_input_tokens + (requested_output_tokens or 0)
    estimated_usage = UsageAccounting(
        prompt_tokens=estimated_input_tokens,
        completion_tokens=requested_output_tokens,
        total_tokens=requested_total_tokens if requested_output_tokens is not None else None,
        usage_source="estimated",
    )
    estimated_cost_cents = _calculate_cost_cents(resolved=resolved, usage=estimated_usage)
    estimated_cost_micro_cents = _calculate_cost_micro_cents(
        resolved=resolved, usage=estimated_usage
    )
    # Reservations expire well beyond the maximum request lifetime (provider timeout
    # up to 300s plus retries and streaming drain) so a slow request is not silently
    # under-counted by the active-reservation summary before it finalizes.
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    # Serialize the read-decide-reserve critical section per resolved counter so
    # concurrent requests for the same limit cannot both pass and overshoot the cap.
    # Locks are acquired in a stable order to avoid deadlocks and released at commit.
    dimension_subject = _limit_dimension_subject(
        resolved=resolved,
        gateway_endpoint=gateway_endpoint,
    )
    matched_limits = [
        limit
        for limit in resolved.limit_policies
        if (limit_types is None or limit.limit_type in limit_types)
        and await _limit_rule_matches_runtime_subject(
            limit=limit,
            subject=dimension_subject,
            db=db,
        )
    ]
    dimension_snapshot = to_dimension_snapshot(
        dimension_subject,
        stage=PolicyDimensionStage.LIMIT_RESERVATION,
    )
    for counter_identity in sorted(
        {
            await _limit_rule_counter_identity(
                org_id=resolved.org_id,
                limit=limit,
                subject=dimension_subject,
                db=db,
            )
            for limit in matched_limits
        }
    ):
        await usage_facade.acquire_limit_counter_lock(identity=counter_identity, db=db)
    for limit in matched_limits:
        if limit.limit_type == "input_tokens" and estimated_input_tokens > limit.limit_value:
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy input token limit exceeded",
                reason="input_token_limit",
                current_usage=estimated_input_tokens,
                reserved_usage=0,
                attempted_usage=estimated_input_tokens,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                dimension_snapshot=dimension_snapshot,
                db=db,
            )
        if (
            limit.limit_type == "output_tokens"
            and requested_output_tokens is not None
            and requested_output_tokens > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy output token limit exceeded",
                reason="output_token_limit",
                current_usage=requested_output_tokens,
                reserved_usage=0,
                attempted_usage=requested_output_tokens,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                dimension_snapshot=dimension_snapshot,
                db=db,
            )
        if limit.limit_type == "tokens_per_request" and requested_total_tokens > limit.limit_value:
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy request token limit exceeded",
                reason="request_token_limit",
                current_usage=requested_total_tokens,
                reserved_usage=0,
                attempted_usage=requested_total_tokens,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                dimension_snapshot=dimension_snapshot,
                db=db,
            )

        since = _limit_policy_window_start(limit.interval_unit, limit.interval_count)
        window_descriptor = _limit_policy_window_descriptor(limit)
        counter_key = await _limit_rule_counter_key(
            limit=limit,
            subject=dimension_subject,
            db=db,
        )
        counting_unit = await _limit_rule_counting_unit(
            org_id=resolved.org_id,
            limit=limit,
            db=db,
        )
        (
            request_count,
            prompt_tokens,
            completion_tokens,
            cost_cents,
            cost_micro_cents,
        ) = await usage_facade.summarize_limit_policy_usage(
            limit_policy_id=limit.limit_policy_id,
            limit_policy_rule_id=limit.limit_policy_rule_id,
            limit_policy_assignment_id=limit.limit_policy_assignment_id,
            counter_key=counter_key,
            counting_unit=counting_unit,
            window_descriptor=window_descriptor,
            since=since,
            db=db,
        )
        reservations = await usage_facade.summarize_active_limit_policy_reservations(
            limit_policy_id=limit.limit_policy_id,
            limit_policy_rule_id=limit.limit_policy_rule_id,
            limit_policy_assignment_id=limit.limit_policy_assignment_id,
            counter_key=counter_key,
            counting_unit=counting_unit,
            window_descriptor=window_descriptor,
            since=since,
            now=datetime.now(UTC),
            db=db,
        )
        if limit.limit_type == "requests" and request_count + 1 > limit.limit_value:
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy request limit exceeded",
                reason="request_limit",
                current_usage=request_count,
                reserved_usage=0,
                attempted_usage=1,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                dimension_snapshot=dimension_snapshot,
                db=db,
            )
        if (
            limit.limit_type == "requests"
            and request_count + reservations.requests + 1 > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy request limit exceeded",
                reason="request_limit",
                current_usage=request_count,
                reserved_usage=reservations.requests,
                attempted_usage=1,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                dimension_snapshot=dimension_snapshot,
                db=db,
            )
        if (
            limit.limit_type == "input_tokens"
            and prompt_tokens + reservations.prompt_tokens + estimated_input_tokens
            > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy input token limit exceeded",
                reason="input_token_limit",
                current_usage=prompt_tokens,
                reserved_usage=reservations.prompt_tokens,
                attempted_usage=estimated_input_tokens,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                dimension_snapshot=dimension_snapshot,
                db=db,
            )
        if (
            limit.limit_type == "output_tokens"
            and requested_output_tokens is not None
            and completion_tokens + reservations.completion_tokens + requested_output_tokens
            > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy output token limit exceeded",
                reason="output_token_limit",
                current_usage=completion_tokens,
                reserved_usage=reservations.completion_tokens,
                attempted_usage=requested_output_tokens,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                db=db,
            )
        if limit.limit_type == "budget_cents":
            if estimated_cost_micro_cents is None:
                # Fail closed: a budget cap cannot be honored for a model with no
                # configured pricing, so deny rather than silently letting it pass.
                await _raise_proxy_denial(
                    resolved=resolved,
                    limit=limit,
                    detail="budget limit cannot be enforced: model has no configured pricing",
                    reason="budget_unpriced",
                    current_usage=cost_cents,
                    reserved_usage=reservations.cost_cents,
                    attempted_usage=None,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    dimension_snapshot=dimension_snapshot,
                    db=db,
                )
            # Budget math is in exact micro-cents (1_000_000 == 1 cent) to avoid the
            # per-request rounding drift that would otherwise mis-gate the cap.
            elif (
                cost_micro_cents + reservations.cost_micro_cents + estimated_cost_micro_cents
                > limit.limit_value * 1_000_000
            ):
                await _raise_proxy_denial(
                    resolved=resolved,
                    limit=limit,
                    detail="limit policy budget exceeded",
                    reason="budget_limit",
                    current_usage=cost_cents,
                    reserved_usage=reservations.cost_cents,
                    attempted_usage=estimated_cost_cents,
                    gateway_request_id=gateway_request_id,
                    route_attempt_id=route_attempt_id,
                    gateway_endpoint=gateway_endpoint,
                    dimension_snapshot=dimension_snapshot,
                    db=db,
                )
        if (
            limit.limit_type == "total_tokens"
            and prompt_tokens
            + completion_tokens
            + reservations.prompt_tokens
            + reservations.completion_tokens
            + requested_total_tokens
            > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                limit=limit,
                detail="limit policy total token limit exceeded",
                reason="total_token_limit",
                current_usage=prompt_tokens + completion_tokens,
                reserved_usage=reservations.prompt_tokens + reservations.completion_tokens,
                attempted_usage=requested_total_tokens,
                gateway_request_id=gateway_request_id,
                route_attempt_id=route_attempt_id,
                gateway_endpoint=gateway_endpoint,
                dimension_snapshot=dimension_snapshot,
                db=db,
            )
    reservation_ids: list[UUID] = []
    for limit in matched_limits:
        if limit.limit_type == "tokens_per_request":
            continue
        counter_key = await _limit_rule_counter_key(
            limit=limit,
            subject=dimension_subject,
            db=db,
        )
        counting_unit = await _limit_rule_counting_unit(
            org_id=resolved.org_id,
            limit=limit,
            db=db,
        )
        window_descriptor = _limit_policy_window_descriptor(limit)
        reservation_id = await usage_facade.create_limit_policy_reservation(
            payload=RecordLimitPolicyReservation(
                org_id=resolved.org_id,
                limit_policy_id=limit.limit_policy_id,
                limit_policy_revision_id=limit.limit_policy_revision_id,
                limit_policy_rule_id=limit.limit_policy_rule_id,
                limit_policy_assignment_id=limit.limit_policy_assignment_id,
                virtual_key_id=resolved.virtual_key_id,
                request_id=current_request_id(),
                counter_key=counter_key,
                counting_unit=counting_unit,
                window_descriptor=window_descriptor,
                dimension_snapshot=dimension_snapshot,
                reserved_prompt_tokens=estimated_input_tokens,
                reserved_completion_tokens=requested_output_tokens or 0,
                reserved_total_tokens=requested_total_tokens,
                reserved_cost_cents=estimated_cost_cents,
                reserved_cost_micro_cents=estimated_cost_micro_cents,
                expires_at=expires_at,
            ),
            db=db,
        )
        reservation_ids.append(reservation_id)
        await _record_gateway_limit_decision(
            resolved=resolved,
            limit=limit,
            gateway_request_id=gateway_request_id,
            route_attempt_id=route_attempt_id,
            stage="limit_reservation",
            outcome="reserved",
            effective_action="allow",
            reason_code="limit_reserved",
            message=None,
            dimension_snapshot=dimension_snapshot,
            metadata={
                "reservation_id": str(reservation_id),
                "gateway_endpoint": gateway_endpoint,
                "counting_unit": counting_unit,
                "reserved_prompt_tokens": estimated_input_tokens,
                "reserved_completion_tokens": requested_output_tokens or 0,
                "reserved_total_tokens": requested_total_tokens,
                "reserved_cost_cents": estimated_cost_cents,
                "reserved_cost_micro_cents": estimated_cost_micro_cents,
            },
            db=db,
        )
    await db.commit()
    return reservation_ids


def _limit_dimension_subject(
    *,
    resolved: ResolvedAccess,
    gateway_endpoint: str | None,
) -> dict[str, Any]:
    return {
        "org_id": resolved.org_id,
        "team_id": resolved.team_id,
        "project_id": resolved.project_id,
        "virtual_key_id": resolved.virtual_key_id,
        "provider_id": resolved.provider_id,
        "credential_pool_id": resolved.pool_id,
        "provider_credential_id": resolved.provider_key_id,
        "provider_model_offering_id": resolved.model_offering_id,
        "public_model_id": resolved.public_model_id,
        "public_model_name": resolved.public_model_name,
        "route_candidate_id": resolved.route_candidate_id,
        "access_policy_id": resolved.access_policy_id,
        "access_policy_revision_id": resolved.access_policy_revision_id,
        "gateway_endpoint": gateway_endpoint,
        "requested_model": resolved.requested_model,
    }


async def _limit_rule_matches_runtime_subject(
    *,
    limit,
    subject: dict[str, Any],
    db: AsyncSession,
) -> bool:
    matchers = await policies_repository.list_limit_policy_rule_matchers(
        org_id=subject["org_id"],
        rule_id=limit.limit_policy_rule_id,
        db=db,
    )
    for matcher in matchers:
        if not evaluate_matcher(
            subject=subject,
            dimension=matcher.dimension,
            operator=matcher.operator,
            value=matcher.value_json,
            stage=PolicyDimensionStage.LIMIT_RESERVATION,
        ):
            return False
    return True


async def _limit_rule_counter_key(
    *,
    limit,
    subject: dict[str, Any],
    db: AsyncSession,
) -> str | None:
    partitions = await policies_repository.list_limit_policy_rule_partitions(
        org_id=subject["org_id"],
        rule_id=limit.limit_policy_rule_id,
        db=db,
    )
    if not partitions:
        return None
    parts = []
    for partition in partitions:
        value = subject.get(partition.dimension)
        parts.append(f"{partition.dimension}={value}")
    return "|".join(parts)


async def _limit_rule_counter_identity(
    *,
    org_id: UUID,
    limit,
    subject: dict[str, Any],
    db: AsyncSession,
) -> str:
    counter_key = await _limit_rule_counter_key(limit=limit, subject=subject, db=db)
    counting_unit = await _limit_rule_counting_unit(org_id=org_id, limit=limit, db=db)
    window_descriptor = _limit_policy_window_descriptor(limit)
    return "|".join(
        (
            str(org_id),
            str(limit.limit_policy_id),
            str(limit.limit_policy_rule_id),
            str(limit.limit_policy_assignment_id),
            window_descriptor,
            counting_unit,
            counter_key or "unpartitioned",
        )
    )


async def _limit_rule_counting_unit(*, org_id: UUID, limit, db: AsyncSession) -> str:
    if limit.limit_type != "requests":
        return "logical_request"
    matchers = await policies_repository.list_limit_policy_rule_matchers(
        org_id=org_id,
        rule_id=limit.limit_policy_rule_id,
        db=db,
    )
    partitions = await policies_repository.list_limit_policy_rule_partitions(
        org_id=org_id,
        rule_id=limit.limit_policy_rule_id,
        db=db,
    )
    dimensions = {matcher.dimension for matcher in matchers} | {
        partition.dimension for partition in partitions
    }
    if dimensions & ATTEMPT_SCOPED_DIMENSIONS:
        return "route_attempt"
    return "logical_request"


async def _usage_limit_counter_key(
    *,
    resolved: ResolvedAccess,
    subject: dict[str, Any],
    db: AsyncSession,
) -> str | None:
    counter_keys = {
        counter_key
        for limit in resolved.limit_policies
        if (
            counter_key := await _limit_rule_counter_key(
                limit=limit,
                subject=subject,
                db=db,
            )
        )
        is not None
    }
    if len(counter_keys) == 1:
        return next(iter(counter_keys))
    return None


async def _usage_limit_window_descriptor(*, resolved: ResolvedAccess) -> str | None:
    descriptors = {
        _limit_policy_window_descriptor(limit)
        for limit in resolved.limit_policies
        if limit.limit_type != "tokens_per_request"
    }
    if len(descriptors) == 1:
        return next(iter(descriptors))
    return None


async def _usage_limit_counting_unit(*, resolved: ResolvedAccess, db: AsyncSession) -> str:
    counting_units = {
        await _limit_rule_counting_unit(org_id=resolved.org_id, limit=limit, db=db)
        for limit in resolved.limit_policies
        if limit.limit_type == "requests"
    }
    if counting_units == {"route_attempt"}:
        return "route_attempt"
    return "logical_request"


async def _commit_reservations(
    *,
    reservation_ids: list[UUID],
    usage: UsageAccounting,
    cost_cents: int | None,
    db: AsyncSession,
) -> None:
    await usage_facade.commit_limit_policy_reservations(
        reservation_ids=reservation_ids,
        usage=usage,
        cost_cents=cost_cents,
        db=db,
    )
    await db.commit()


async def _release_reservations(*, reservation_ids: list[UUID], db: AsyncSession) -> None:
    await usage_facade.release_limit_policy_reservations(reservation_ids=reservation_ids, db=db)
    await db.commit()


class ProxyLimitExceededError(Exception):
    """A limit policy denied the request. Carries the 429 detail for the handler,
    which releases any reservations already taken before responding."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def _raise_proxy_denial(
    *,
    resolved,
    limit,
    detail: str,
    reason: str,
    current_usage: int | None,
    reserved_usage: int | None,
    attempted_usage: int | None,
    gateway_request_id: UUID | None = None,
    route_attempt_id: UUID | None = None,
    gateway_endpoint: str | None = None,
    dimension_snapshot: dict[str, Any] | None = None,
    db: AsyncSession,
) -> None:
    metadata = {
        "reason": reason,
        "limit_policy_id": str(limit.limit_policy_id),
        "limit_policy_name": limit.limit_policy_name,
        "limit_policy_rule_id": str(limit.limit_policy_rule_id),
        "limit_policy_rule_name": limit.name,
        "limit_policy_assignment_id": str(limit.limit_policy_assignment_id),
        "limit_policy_assignment_scope": "resolved",
        "limit_type": limit.limit_type,
        "current_usage": current_usage,
        "reserved_usage": reserved_usage,
        "attempted_usage": attempted_usage,
        "configured_limit": limit.limit_value,
        "interval_unit": limit.interval_unit,
        "interval_count": limit.interval_count,
    }
    await _record_gateway_limit_decision(
        resolved=resolved,
        limit=limit,
        gateway_request_id=gateway_request_id,
        route_attempt_id=route_attempt_id,
        stage="limit_reservation",
        outcome="denied",
        effective_action="deny",
        reason_code=reason,
        message=detail,
        dimension_snapshot=dimension_snapshot,
        metadata={
            "gateway_endpoint": gateway_endpoint,
            "current_usage": current_usage,
            "reserved_usage": reserved_usage,
            "attempted_usage": attempted_usage,
        },
        db=db,
    )
    await _record_proxy_request(
        resolved=resolved,
        gateway_request_id=gateway_request_id,
        http_status=status.HTTP_429_TOO_MANY_REQUESTS,
        latency_ms=0,
        usage=unknown_usage(),
        error_code="limit_policy_denied",
        gateway_endpoint=gateway_endpoint,
        db=db,
    )
    await _record_proxy_activity(
        resolved=resolved,
        action="proxy.denied",
        message=detail,
        severity="warning",
        metadata=metadata,
        gateway_request_id=gateway_request_id,
        db=db,
    )
    # Raise a domain error (not HTTPException) so the request handler can release
    # any reservations taken in an earlier enforcement phase before returning 429.
    raise ProxyLimitExceededError(detail)


async def _record_gateway_limit_decision(
    *,
    resolved,
    limit,
    gateway_request_id: UUID | None,
    route_attempt_id: UUID | None,
    stage: str,
    outcome: str,
    effective_action: str,
    reason_code: str,
    message: str | None,
    dimension_snapshot: dict[str, Any] | None = None,
    metadata: dict,
    db: AsyncSession,
) -> None:
    if gateway_request_id is None:
        return
    assignment = await policies_repository.get_policy_assignment(
        assignment_id=limit.limit_policy_assignment_id,
        org_id=resolved.org_id,
        db=db,
    )
    await usage_facade.create_gateway_policy_decision(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": gateway_request_id,
            "route_attempt_id": route_attempt_id,
            "decision_type": "limit",
            "stage": stage,
            "outcome": outcome,
            "effective_action": effective_action,
            "enforced": True,
            "policy_id": assignment.policy_id if assignment else None,
            "policy_revision_id": limit.limit_policy_revision_id,
            "assignment_id": limit.limit_policy_assignment_id,
            "assignment_mode": assignment.mode if assignment else None,
            "assignment_scope_type": assignment.scope_type if assignment else None,
            "assignment_team_id": assignment.team_id if assignment else None,
            "assignment_project_id": assignment.project_id if assignment else None,
            "assignment_virtual_key_id": assignment.virtual_key_id if assignment else None,
            "rule_id": limit.limit_policy_rule_id,
            "route_candidate_id": resolved.route_candidate_id,
            "reason_code": reason_code,
            "message": message,
            "dimension_snapshot": {
                **(dimension_snapshot or {}),
                "limit_type": limit.limit_type,
            },
            "metadata_": {
                **metadata,
                "limit_policy_id": str(limit.limit_policy_id),
                "limit_policy_name": limit.limit_policy_name,
                "limit_policy_rule_id": str(limit.limit_policy_rule_id),
                "limit_policy_rule_name": limit.name,
                "limit_policy_assignment_id": str(limit.limit_policy_assignment_id),
                "configured_limit": limit.limit_value,
                "interval_unit": limit.interval_unit,
                "interval_count": limit.interval_count,
            },
        },
        db=db,
    )


async def _evaluate_guardrail_request(
    *,
    context: GuardrailEvaluationContext,
    resolved: ResolvedAccess,
    db: AsyncSession,
) -> None:
    try:
        evaluated = await guardrails_facade.evaluate_request(context=context, db=db)
    except GuardrailDeniedError as exc:
        await _record_gateway_guardrail_decision(
            context=context,
            resolved=resolved,
            stage="request_guardrail",
            outcome="denied",
            effective_action="deny",
            reason_code="guardrail_denied",
            message=exc.detail,
            policy_id=exc.policy_id,
            policy_revision_id=exc.policy_revision_id,
            assignment_id=exc.assignment_id,
            assignment_mode=exc.assignment_mode,
            assignment_scope_type=exc.assignment_scope_type,
            assignment_team_id=exc.assignment_team_id,
            assignment_project_id=exc.assignment_project_id,
            assignment_virtual_key_id=exc.assignment_virtual_key_id,
            rule_id=exc.rule_id,
            db=db,
        )
        raise
    if evaluated:
        for trace in evaluated.would_deny:
            await _record_gateway_guardrail_decision(
                context=context,
                resolved=resolved,
                stage="request_guardrail",
                outcome="would_deny",
                effective_action="would_deny",
                reason_code=trace.reason_code,
                message=trace.message,
                policy_id=trace.policy_id,
                policy_revision_id=trace.policy_revision_id,
                assignment_id=trace.assignment_id,
                assignment_mode=trace.assignment_mode,
                assignment_scope_type=trace.assignment_scope_type,
                assignment_team_id=trace.assignment_team_id,
                assignment_project_id=trace.assignment_project_id,
                assignment_virtual_key_id=trace.assignment_virtual_key_id,
                rule_id=trace.rule_id,
                db=db,
            )
        await _record_gateway_guardrail_decision(
            context=context,
            resolved=resolved,
            stage="request_guardrail",
            outcome="allowed",
            effective_action="allow",
            reason_code="request_guardrails_passed",
            message=None,
            policy_id=None,
            policy_revision_id=None,
            assignment_id=None,
            assignment_mode=None,
            assignment_scope_type=None,
            assignment_team_id=None,
            assignment_project_id=None,
            assignment_virtual_key_id=None,
            rule_id=None,
            db=db,
        )


async def _evaluate_guardrail_response(
    *,
    context: GuardrailEvaluationContext,
    resolved: ResolvedAccess,
    response_text: str,
    db: AsyncSession,
) -> None:
    response_context = context.model_copy(update={"phase": "response"})
    try:
        evaluated = await guardrails_facade.evaluate_response(
            context=context,
            response_text=response_text,
            db=db,
        )
    except GuardrailDeniedError as exc:
        await _record_gateway_guardrail_decision(
            context=response_context,
            resolved=resolved,
            stage="response_guardrail",
            outcome="denied",
            effective_action="deny",
            reason_code="guardrail_output_denied",
            message=exc.detail,
            policy_id=exc.policy_id,
            policy_revision_id=exc.policy_revision_id,
            assignment_id=exc.assignment_id,
            assignment_mode=exc.assignment_mode,
            assignment_scope_type=exc.assignment_scope_type,
            assignment_team_id=exc.assignment_team_id,
            assignment_project_id=exc.assignment_project_id,
            assignment_virtual_key_id=exc.assignment_virtual_key_id,
            rule_id=exc.rule_id,
            db=db,
        )
        raise
    if evaluated:
        for trace in evaluated.would_deny:
            await _record_gateway_guardrail_decision(
                context=response_context,
                resolved=resolved,
                stage="response_guardrail",
                outcome="would_deny",
                effective_action="would_deny",
                reason_code=trace.reason_code,
                message=trace.message,
                policy_id=trace.policy_id,
                policy_revision_id=trace.policy_revision_id,
                assignment_id=trace.assignment_id,
                assignment_mode=trace.assignment_mode,
                assignment_scope_type=trace.assignment_scope_type,
                assignment_team_id=trace.assignment_team_id,
                assignment_project_id=trace.assignment_project_id,
                assignment_virtual_key_id=trace.assignment_virtual_key_id,
                rule_id=trace.rule_id,
                db=db,
            )
        await _record_gateway_guardrail_decision(
            context=response_context,
            resolved=resolved,
            stage="response_guardrail",
            outcome="allowed",
            effective_action="allow",
            reason_code="response_guardrails_passed",
            message=None,
            policy_id=None,
            policy_revision_id=None,
            assignment_id=None,
            assignment_mode=None,
            assignment_scope_type=None,
            assignment_team_id=None,
            assignment_project_id=None,
            assignment_virtual_key_id=None,
            rule_id=None,
            db=db,
        )


async def _record_gateway_guardrail_decision(
    *,
    context: GuardrailEvaluationContext,
    resolved: ResolvedAccess,
    stage: str,
    outcome: str,
    effective_action: str,
    reason_code: str,
    message: str | None,
    policy_id: UUID | None,
    policy_revision_id: UUID | None,
    assignment_id: UUID | None,
    assignment_mode: str | None,
    assignment_scope_type: str | None,
    assignment_team_id: UUID | None,
    assignment_project_id: UUID | None,
    assignment_virtual_key_id: UUID | None,
    rule_id: UUID | None,
    db: AsyncSession,
) -> None:
    if context.gateway_request_id is None:
        return
    shared_policy_id = policy_id
    if policy_id is not None:
        policy = await guardrails_repository.get_policy(
            policy_id=policy_id,
            org_id=resolved.org_id,
            db=db,
        )
        if policy is not None and policy.policy_id is not None:
            shared_policy_id = policy.policy_id
    await usage_facade.create_gateway_policy_decision(
        values={
            "org_id": resolved.org_id,
            "gateway_request_id": context.gateway_request_id,
            "route_attempt_id": context.route_attempt_id,
            "decision_type": "guardrail",
            "stage": stage,
            "outcome": outcome,
            "effective_action": effective_action,
            "enforced": outcome != "would_deny",
            "policy_id": shared_policy_id,
            "policy_revision_id": policy_revision_id,
            "assignment_id": assignment_id,
            "assignment_mode": assignment_mode,
            "assignment_scope_type": assignment_scope_type,
            "assignment_team_id": assignment_team_id,
            "assignment_project_id": assignment_project_id,
            "assignment_virtual_key_id": assignment_virtual_key_id,
            "rule_id": rule_id,
            "route_candidate_id": resolved.route_candidate_id,
            "reason_code": reason_code,
            "message": message,
            "dimension_snapshot": {
                "phase": context.phase,
                "virtual_key_id": str(resolved.virtual_key_id),
                "public_model_id": str(resolved.public_model_id),
                "provider_id": str(resolved.provider_id),
                "pool_id": str(resolved.pool_id),
                "route_candidate_id": str(resolved.route_candidate_id),
            },
            "metadata_": {
                "guardrail_policy_revision_id": str(policy_revision_id)
                if policy_revision_id
                else None,
                "legacy_guardrail_rule_id": str(rule_id) if rule_id else None,
                "requested_model": context.requested_model,
                "provider_model": context.provider_model,
            },
        },
        db=db,
    )


async def _record_proxy_activity(
    *,
    resolved,
    action: str,
    message: str,
    severity: str,
    metadata: dict,
    db: AsyncSession,
    gateway_request_id: UUID | None = None,
) -> None:
    await activity_facade.record_event_and_commit(
        payload=RecordActivityEvent(
            org_id=resolved.org_id,
            category="proxy",
            severity=severity,
            action=action,
            message=message,
            team_id=resolved.team_id,
            project_id=resolved.project_id,
            virtual_key_id=resolved.virtual_key_id,
            provider_id=resolved.provider_id,
            pool_id=resolved.pool_id,
            request_id=current_request_id(),
            gateway_request_id=gateway_request_id,
            metadata={
                **metadata,
                "requested_model": resolved.requested_model,
                "provider_model": resolved.provider_model,
            },
        ),
        db=db,
    )


def _requested_output_tokens(extra_body: dict[str, Any]) -> int | None:
    value = extra_body.get("max_tokens") or extra_body.get("max_completion_tokens")
    if isinstance(value, int) and value > 0:
        return value
    return None


def _limit_policy_window_start(interval_unit: str, interval_count: int) -> datetime | None:
    now = datetime.now(UTC)
    if interval_unit == "minute":
        return now - timedelta(minutes=interval_count)
    if interval_unit == "hour":
        return now - timedelta(hours=interval_count)
    if interval_unit == "day":
        return now - timedelta(days=interval_count)
    if interval_unit == "week":
        return now - timedelta(weeks=interval_count)
    if interval_unit == "month":
        return subtract_months(now, interval_count)
    return None


def _limit_policy_window_descriptor(limit) -> str:
    if limit.interval_unit == "lifetime":
        return f"{limit.interval_unit}:{limit.interval_count}:lifetime"
    return f"{limit.interval_unit}:{limit.interval_count}:rolling"


def _costing_context(resolved) -> CostingContext:
    return CostingContext(
        provider_id=str(resolved.provider_id),
        provider_model=resolved.provider_model,
        input_price_per_million_tokens=resolved.input_price_per_million_tokens,
        output_price_per_million_tokens=resolved.output_price_per_million_tokens,
    )


def _calculate_cost_cents(*, resolved, usage: UsageAccounting) -> int | None:
    return default_cost_calculator_registry.calculate_cents(
        context=_costing_context(resolved),
        usage=usage,
    )


def _calculate_cost_micro_cents(*, resolved, usage: UsageAccounting) -> int | None:
    return default_cost_calculator_registry.calculate_micro_cents(
        context=_costing_context(resolved),
        usage=usage,
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
