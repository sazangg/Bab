import json
from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.database import Scope, get_db
from app.core.problems import ProblemException
from app.modules.gateway import failures as gateway_failures
from app.modules.gateway import guardrails as gateway_guardrails
from app.modules.gateway import limits as gateway_limits
from app.modules.gateway import provider_execution as gateway_provider_execution
from app.modules.gateway import response_finalization as gateway_response_finalization
from app.modules.gateway import streaming as gateway_streaming
from app.modules.gateway import tracing as gateway_tracing
from app.modules.keys import facade as keys_runtime_facade
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
)
from app.modules.keys.schemas import (
    ResolveAccessPlanForSubjectRequest,
    ResolvedAccessPlan,
    ResolveKeySubjectRequest,
)
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

router = APIRouter(prefix="/v1", tags=["proxy"])
logger = structlog.get_logger(__name__)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
VirtualKeyAuthorization = Annotated[str | None, Header(alias="Authorization")]
ProviderIdHeader = Annotated[UUID | None, Header(alias="X-Bab-Provider-Id")]
AnthropicApiKey = Annotated[str | None, Header(alias="x-api-key")]


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
        models = await keys_runtime_facade.list_accessible_models(raw_key=raw_key, db=db)
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
    return await _handle_openai_compatible_proxy(
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
    return await _handle_openai_compatible_proxy(
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
        return await _handle_openai_compatible_proxy(
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
    current_route_attempt_id: UUID | None = None
    reservation_ids: list[UUID] = []
    execution_state = gateway_provider_execution.ProviderExecutionState()

    def sync_execution_state() -> None:
        nonlocal resolved
        nonlocal reservation_ids
        nonlocal current_route_attempt_id
        resolved = execution_state.resolved or resolved
        reservation_ids = execution_state.reservation_ids
        current_route_attempt_id = execution_state.current_route_attempt_id

    try:
        gateway_request_id = await gateway_tracing.create_gateway_request(
            resolved=None,
            requested_model=provider_payload.model,
            gateway_endpoint="chat_completions",
            db=db,
        )
        key_subject = await keys_runtime_facade.resolve_key_subject(
            payload=ResolveKeySubjectRequest(raw_key=raw_key),
            db=db,
        )
        await gateway_tracing.attach_gateway_request_subject(
            gateway_request_id=gateway_request_id,
            key_subject=key_subject,
            db=db,
        )
        plan = await keys_runtime_facade.resolve_access_plan_for_subject(
            payload=ResolveAccessPlanForSubjectRequest(
                subject=key_subject,
                requested_model=provider_payload.model,
                provider_id=provider_id,
                streaming=is_streaming,
                gateway_endpoint="chat_completions",
            ),
            db=db,
        )
        resolved = gateway_provider_execution.resolved_access_from_attempt(
            plan=plan,
            attempt_index=0,
        )
        await gateway_tracing.attach_gateway_request_resolution(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
        org_settings = await settings_facade.get_organization_settings(
            scope=Scope(org_id=resolved.org_id),
            db=db,
        )
        _enforce_body_size(raw_body, org_settings.default_max_body_bytes)
        streaming_result = await gateway_streaming.prepare_openai_compatible_streaming(
            plan=plan,
            provider_payload=provider_payload,
            raw_body=raw_body,
            provider_id=provider_id,
            gateway_request_id=gateway_request_id,
            state=execution_state,
            db=db,
            http_client=http_client,
        )
        resolved = streaming_result.resolved
        reservation_ids = streaming_result.reservation_ids
        current_route_attempt_id = streaming_result.route_attempt_id
        return StreamingResponse(
            gateway_streaming.stream_openai_compatible_response(
                result=streaming_result,
                started_at=started_at,
                db=db,
            ),
            status_code=streaming_result.upstream.status_code,
            media_type=streaming_result.upstream.media_type,
        )
    except InvalidVirtualKeyError as exc:
        await gateway_failures.finalize_invalid_virtual_key(
            gateway_request_id=gateway_request_id,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except gateway_streaming.StreamingBlockedByResponseGuardrailError as exc:
        sync_execution_state()
        await gateway_failures.finalize_streaming_response_guardrail_blocked(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        ) from exc
    except gateway_provider_execution.ProviderBodyTooLargeError as exc:
        sync_execution_state()
        await gateway_failures.finalize_request_body_too_large(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=exc.detail,
        ) from exc
    except HTTPException as exc:
        if exc.status_code != status.HTTP_413_CONTENT_TOO_LARGE:
            raise
        await gateway_failures.finalize_request_body_too_large(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            db=db,
        )
        raise
    except gateway_limits.GatewayLimitDeniedError as exc:
        sync_execution_state()
        await gateway_failures.finalize_limit_denial(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            denial=exc,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
        ) from exc
    except AccessDeniedError as exc:
        sync_execution_state()
        await gateway_failures.finalize_access_denied(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            message="Proxy request denied by access, limit, or provider routing policy.",
            record_usage=False,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except gateway_guardrails.GatewayGuardrailDenied as exc:
        sync_execution_state()
        await gateway_failures.finalize_request_guardrail_denied(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            denial=exc,
            record_usage=True,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.detail,
        ) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError, ProviderNotFoundError) as exc:
        sync_execution_state()
        await gateway_failures.finalize_provider_unavailable(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            message="Proxy request failed because the provider is unavailable.",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider is not available",
        ) from exc
    except ProviderUpstreamError as exc:
        sync_execution_state()
        await gateway_failures.finalize_provider_upstream_error(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                reservation_ids=reservation_ids,
                started_at=started_at,
                gateway_endpoint="chat_completions",
            ),
            error=exc,
            unavailable_message="Proxy request failed with an upstream provider error.",
            fallback_exhausted_message=None,
            upstream_failed_message="Proxy request failed with an upstream provider error.",
            finalize_route_attempt=True,
            activity_action="proxy.provider_error",
            provider_error_metadata={"status_code": exc.status_code},
            db=db,
        )
        _raise_provider_upstream_problem(exc)


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
    guardrail_context = None
    selected_attempt_index = 0
    current_route_attempt_id: UUID | None = None
    final_route_attempt_id: UUID | None = None
    execution_state = gateway_provider_execution.ProviderExecutionState()

    def sync_execution_state() -> None:
        nonlocal resolved
        nonlocal reservation_ids
        nonlocal current_route_attempt_id
        nonlocal final_route_attempt_id
        nonlocal attempted_routes
        nonlocal selected_attempt_index
        nonlocal fallback_attempted
        resolved = execution_state.resolved or resolved
        reservation_ids = execution_state.reservation_ids
        current_route_attempt_id = execution_state.current_route_attempt_id
        final_route_attempt_id = execution_state.final_route_attempt_id
        attempted_routes = execution_state.attempted_routes
        selected_attempt_index = execution_state.selected_attempt_index
        fallback_attempted = execution_state.fallback_attempted

    try:
        gateway_request_id = await gateway_tracing.create_gateway_request(
            resolved=None,
            requested_model=provider_payload.model,
            gateway_endpoint="anthropic_messages",
            db=db,
        )
        key_subject = await keys_runtime_facade.resolve_key_subject(
            payload=ResolveKeySubjectRequest(raw_key=raw_key),
            db=db,
        )
        await gateway_tracing.attach_gateway_request_subject(
            gateway_request_id=gateway_request_id,
            key_subject=key_subject,
            db=db,
        )
        plan = await keys_runtime_facade.resolve_access_plan_for_subject(
            payload=ResolveAccessPlanForSubjectRequest(
                subject=key_subject,
                requested_model=provider_payload.model,
                provider_id=provider_id,
                gateway_endpoint="anthropic_messages",
            ),
            db=db,
        )
        resolved = gateway_provider_execution.resolved_access_from_attempt(
            plan=plan,
            attempt_index=0,
        )
        await gateway_tracing.attach_gateway_request_resolution(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
        org_settings = await settings_facade.get_organization_settings(
            scope=Scope(org_id=resolved.org_id),
            db=db,
        )
        _enforce_body_size(raw_body, org_settings.default_max_body_bytes)
        await gateway_tracing.record_gateway_access_decision(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
        execution_result = await gateway_provider_execution.execute_native_anthropic_non_streaming(
            plan=plan,
            provider_payload=provider_payload,
            raw_body=raw_body,
            gateway_request_id=gateway_request_id,
            gateway_endpoint="anthropic_messages",
            anthropic_version=anthropic_version,
            started_at=started_at,
            state=execution_state,
            db=db,
            http_client=http_client,
        )
        resolved = execution_result.resolved
        upstream = execution_result.upstream
        reservation_ids = execution_result.reservation_ids
        guardrail_context = execution_result.guardrail_context
        final_route_attempt_id = execution_result.final_route_attempt_id
        current_route_attempt_id = execution_state.current_route_attempt_id
        attempted_routes = execution_result.attempted_routes
        selected_attempt_index = execution_result.selected_attempt_index
        fallback_attempted = execution_result.fallback_attempted
    except gateway_provider_execution.ProviderBodyTooLargeError as exc:
        sync_execution_state()
        await gateway_failures.finalize_request_body_too_large(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint="anthropic_messages",
            ),
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=exc.detail,
        ) from exc
    except InvalidVirtualKeyError as exc:
        await gateway_failures.finalize_invalid_virtual_key(
            gateway_request_id=gateway_request_id,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except HTTPException as exc:
        if exc.status_code != status.HTTP_413_CONTENT_TOO_LARGE:
            raise
        await gateway_failures.finalize_request_body_too_large(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint="anthropic_messages",
            ),
            db=db,
        )
        raise
    except gateway_limits.GatewayLimitDeniedError as exc:
        sync_execution_state()
        await gateway_failures.finalize_limit_denial(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint="anthropic_messages",
            ),
            denial=exc,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
        ) from exc
    except AccessDeniedError as exc:
        sync_execution_state()
        await gateway_failures.finalize_access_denied(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint="anthropic_messages",
            ),
            message="Native Anthropic request denied by access or provider routing policy.",
            record_usage=True,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except gateway_guardrails.GatewayGuardrailDenied as exc:
        sync_execution_state()
        await gateway_failures.finalize_request_guardrail_denied(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint="anthropic_messages",
            ),
            denial=exc,
            record_usage=True,
            db=db,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError, ProviderNotFoundError) as exc:
        sync_execution_state()
        await gateway_failures.finalize_provider_unavailable(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint="anthropic_messages",
            ),
            message="Native Anthropic provider is not available.",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider is not available",
        ) from exc
    except ProviderUpstreamError as exc:
        sync_execution_state()
        await gateway_failures.finalize_provider_upstream_error(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                selected_attempt_index=selected_attempt_index,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint="anthropic_messages",
            ),
            error=exc,
            unavailable_message="Native Anthropic provider request failed.",
            fallback_exhausted_message="Native Anthropic fallback candidates were exhausted.",
            upstream_failed_message="Native Anthropic provider request failed.",
            finalize_route_attempt=False,
            db=db,
        )
        _raise_provider_upstream_problem(exc)

    try:
        finalized_response = (
            await gateway_response_finalization.finalize_native_anthropic_non_streaming_response(
                resolved=resolved,
                provider_payload=provider_payload,
                upstream=upstream,
                guardrail_context=guardrail_context,
                gateway_request_id=gateway_request_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                selected_attempt_index=selected_attempt_index,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                db=db,
            )
        )
    except gateway_response_finalization.GatewayResponseGuardrailDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    return JSONResponse(
        status_code=finalized_response.status_code,
        content=finalized_response.body,
    )


@router.post("/embeddings", response_model=None)
async def create_embeddings() -> None:
    raise ProblemException(
        problem_type="urn:bab:error:not-implemented",
        title="Not Implemented",
        status=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Embeddings are not implemented yet.",
    )


async def _handle_openai_compatible_proxy(
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
    execution_state = gateway_provider_execution.ProviderExecutionState()

    def sync_execution_state() -> None:
        nonlocal resolved
        nonlocal reservation_ids
        nonlocal current_route_attempt_id
        nonlocal final_route_attempt_id
        nonlocal attempted_routes
        nonlocal selected_attempt_index
        nonlocal fallback_attempted
        resolved = execution_state.resolved or resolved
        reservation_ids = execution_state.reservation_ids
        current_route_attempt_id = execution_state.current_route_attempt_id
        final_route_attempt_id = execution_state.final_route_attempt_id
        attempted_routes = execution_state.attempted_routes
        selected_attempt_index = execution_state.selected_attempt_index
        fallback_attempted = execution_state.fallback_attempted

    try:
        gateway_request_id = await gateway_tracing.create_gateway_request(
            resolved=None,
            requested_model=provider_payload.model,
            gateway_endpoint=gateway_endpoint,
            db=db,
        )
        key_subject = await keys_runtime_facade.resolve_key_subject(
            payload=ResolveKeySubjectRequest(raw_key=raw_key),
            db=db,
        )
        await gateway_tracing.attach_gateway_request_subject(
            gateway_request_id=gateway_request_id,
            key_subject=key_subject,
            db=db,
        )
        plan = await keys_runtime_facade.resolve_access_plan_for_subject(
            payload=ResolveAccessPlanForSubjectRequest(
                subject=key_subject,
                requested_model=provider_payload.model,
                provider_id=provider_id,
                gateway_endpoint=gateway_endpoint,
            ),
            db=db,
        )
        resolved = gateway_provider_execution.resolved_access_from_attempt(
            plan=plan,
            attempt_index=0,
        )
        await gateway_tracing.attach_gateway_request_resolution(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
        org_settings = await settings_facade.get_organization_settings(
            scope=Scope(org_id=resolved.org_id),
            db=db,
        )
        _enforce_body_size(raw_body, org_settings.default_max_body_bytes)
        await gateway_tracing.record_gateway_access_decision(
            gateway_request_id=gateway_request_id,
            resolved=resolved,
            db=db,
        )
        execution_result = await gateway_provider_execution.execute_openai_compatible_non_streaming(
            plan=plan,
            provider_payload=provider_payload,
            raw_body=raw_body,
            gateway_request_id=gateway_request_id,
            gateway_endpoint=gateway_endpoint,
            started_at=started_at,
            state=execution_state,
            db=db,
            http_client=http_client,
        )
        resolved = execution_result.resolved
        upstream = execution_result.upstream
        reservation_ids = execution_result.reservation_ids
        final_route_attempt_id = execution_result.final_route_attempt_id
        current_route_attempt_id = execution_state.current_route_attempt_id
        attempted_routes = execution_result.attempted_routes
        selected_attempt_index = execution_result.selected_attempt_index
        fallback_attempted = execution_result.fallback_attempted
    except gateway_provider_execution.ProviderBodyTooLargeError as exc:
        sync_execution_state()
        await gateway_failures.finalize_request_body_too_large(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint=gateway_endpoint,
            ),
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=exc.detail,
        ) from exc
    except InvalidVirtualKeyError as exc:
        await gateway_failures.finalize_invalid_virtual_key(
            gateway_request_id=gateway_request_id,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except HTTPException as exc:
        if exc.status_code != status.HTTP_413_CONTENT_TOO_LARGE:
            raise
        await gateway_failures.finalize_request_body_too_large(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint=gateway_endpoint,
            ),
            db=db,
        )
        raise
    except gateway_limits.GatewayLimitDeniedError as exc:
        sync_execution_state()
        await gateway_failures.finalize_limit_denial(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint=gateway_endpoint,
            ),
            denial=exc,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
        ) from exc
    except AccessDeniedError as exc:
        sync_execution_state()
        await gateway_failures.finalize_access_denied(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint=gateway_endpoint,
            ),
            message="Proxy request denied by access, limit, or provider routing policy.",
            record_usage=False,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except gateway_guardrails.GatewayGuardrailDenied as exc:
        sync_execution_state()
        await gateway_failures.finalize_request_guardrail_denied(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint=gateway_endpoint,
            ),
            denial=exc,
            record_usage=True,
            db=db,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError, ProviderNotFoundError) as exc:
        sync_execution_state()
        await gateway_failures.finalize_provider_unavailable(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint=gateway_endpoint,
            ),
            message="provider is not available.",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider is not available",
        ) from exc
    except ProviderUpstreamError as exc:
        sync_execution_state()
        await gateway_failures.finalize_provider_upstream_error(
            context=_failure_context(
                resolved=resolved,
                gateway_request_id=gateway_request_id,
                current_route_attempt_id=current_route_attempt_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                attempted_routes=attempted_routes,
                selected_attempt_index=selected_attempt_index,
                fallback_attempted=fallback_attempted,
                started_at=started_at,
                gateway_endpoint=gateway_endpoint,
            ),
            error=exc,
            unavailable_message="provider request failed.",
            fallback_exhausted_message="Fallback candidates were exhausted.",
            upstream_failed_message="provider request failed.",
            finalize_route_attempt=False,
            db=db,
        )
        _raise_provider_upstream_problem(exc)

    try:
        finalized_response = (
            await gateway_response_finalization.finalize_openai_compatible_non_streaming_response(
                resolved=resolved,
                provider_payload=provider_payload,
                upstream=upstream,
                gateway_request_id=gateway_request_id,
                final_route_attempt_id=final_route_attempt_id,
                reservation_ids=reservation_ids,
                selected_attempt_index=selected_attempt_index,
                attempted_routes=attempted_routes,
                fallback_attempted=fallback_attempted,
                gateway_endpoint=gateway_endpoint,
                started_at=started_at,
                db=db,
            )
        )
    except gateway_response_finalization.GatewayResponseGuardrailDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
    return JSONResponse(
        status_code=finalized_response.status_code,
        content=response_transform(finalized_response.body),
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
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="request body is too large",
            )
    # Stream with a running byte counter so a chunked or under-declared body is
    # aborted before the whole payload is buffered into memory. This runs before
    # virtual-key authentication, so it is the guard against unauthenticated OOM.
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_body_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="request body is too large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _enforce_body_size(raw_body: bytes, max_body_bytes: int) -> None:
    if len(raw_body) > max_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="request body is too large",
        )


def _raise_provider_upstream_problem(exc: ProviderUpstreamError) -> None:
    raise ProblemException(
        problem_type="urn:bab:error:provider-upstream",
        title="Upstream Provider Error",
        status=exc.status_code,
        detail="Upstream provider request failed",
        extra={
            "failure_reason": exc.failure_reason,
            "upstream_status": exc.status_code,
        },
    ) from exc


def _failure_context(
    *,
    resolved,
    gateway_request_id: UUID | None,
    current_route_attempt_id: UUID | None,
    final_route_attempt_id: UUID | None = None,
    reservation_ids: list[UUID],
    attempted_routes: int = 0,
    selected_attempt_index: int = 0,
    fallback_attempted: bool = False,
    started_at: float,
    gateway_endpoint: str,
) -> gateway_failures.GatewayFailureContext:
    return gateway_failures.GatewayFailureContext(
        resolved=resolved,
        gateway_request_id=gateway_request_id,
        current_route_attempt_id=current_route_attempt_id,
        final_route_attempt_id=final_route_attempt_id,
        reservation_ids=reservation_ids,
        attempted_routes=attempted_routes,
        selected_attempt_index=selected_attempt_index,
        fallback_attempted=fallback_attempted,
        started_at=started_at,
        gateway_endpoint=gateway_endpoint,
    )


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



