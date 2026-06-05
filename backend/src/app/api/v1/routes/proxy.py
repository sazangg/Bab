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
from app.modules.guardrails.schemas import GuardrailEvaluationContext
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import (
    AccessDeniedError,
    InvalidVirtualKeyError,
)
from app.modules.keys.schemas import ResolveAccessRequest
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
    unknown_usage,
    usage_from_provider_response,
    usage_from_stream_chunks,
)
from app.modules.usage.costing.base import CostingContext
from app.modules.usage.costing.registry import default_cost_calculator_registry
from app.modules.usage.schemas import RecordLimitPolicyReservation, RecordUsage

router = APIRouter(prefix="/v1", tags=["proxy"])
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
    _enforce_content_length(request, settings.proxy_max_body_bytes)
    raw_body = await request.body()
    _enforce_body_size(raw_body, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    if body.get("stream") is True:
        raise HTTPException(status_code=400, detail="streaming completions are not supported")
    chat_body = _completion_body_to_chat_body(body)
    return await _execute_chat_proxy(
        body=chat_body,
        raw_body=raw_body,
        started_at=started_at,
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
    _enforce_content_length(request, settings.proxy_max_body_bytes)
    raw_body = await request.body()
    _enforce_body_size(raw_body, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    if body.get("stream") is True:
        raise HTTPException(status_code=400, detail="streaming responses are not supported")
    chat_body = _responses_body_to_chat_body(body)
    return await _execute_chat_proxy(
        body=chat_body,
        raw_body=raw_body,
        started_at=started_at,
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
    _enforce_content_length(request, settings.proxy_max_body_bytes)
    raw_body = await request.body()
    _enforce_body_size(raw_body, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    is_streaming = body.get("stream") is True

    provider_payload = _to_provider_payload(body)
    raw_key = _extract_bearer_token(authorization)
    resolved = None
    estimated_tokens = 0
    reservation_ids: list[UUID] = []
    try:
        resolved = await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=raw_key,
                requested_model=provider_payload.model,
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
            db=db,
        )
        guardrail_context = _guardrail_context(resolved=resolved, provider_payload=provider_payload)
        await guardrails_facade.evaluate_request(context=guardrail_context, db=db)
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
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
                db=db,
            )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.provider_error",
                message="Proxy request failed with an upstream provider error.",
                severity="error",
                metadata={"status_code": exc.status_code},
                db=db,
            )
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    try:
        await guardrails_facade.evaluate_response(
            context=_guardrail_context(resolved=resolved, provider_payload=provider_payload),
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
    _enforce_content_length(request, settings.proxy_max_body_bytes)
    raw_body = await request.body()
    _enforce_body_size(raw_body, settings.proxy_max_body_bytes)
    body = _decode_json_body(raw_body)
    if body.get("stream") is True:
        raise HTTPException(status_code=400, detail="native Anthropic streaming is not supported")

    provider_payload = _to_anthropic_payload(body)
    raw_key = _extract_anthropic_virtual_key(
        authorization=authorization,
        api_key=anthropic_api_key,
    )
    resolved = None
    reservation_ids: list[UUID] = []
    try:
        resolved = await keys_facade.resolve_access(
            payload=ResolveAccessRequest(raw_key=raw_key, requested_model=provider_payload.model),
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
        if not resolved_provider.integration_capabilities.get("native_anthropic_messages"):
            raise AccessDeniedError
        _enforce_provider_body_size(raw_body, resolved_provider.max_body_bytes)
        estimated_tokens = estimate_request_tokens(provider_payload.messages)
        reservation_ids = await _enforce_limit_policies(
            resolved=resolved,
            estimated_input_tokens=estimated_tokens,
            requested_output_tokens=_requested_output_tokens(provider_payload.extra_body),
            db=db,
        )
        guardrail_payload = ProviderChatCompletionRequest(
            model=provider_payload.model,
            messages=provider_payload.messages,
            extra_body=provider_payload.extra_body,
        )
        await guardrails_facade.evaluate_request(
            context=_guardrail_context(resolved=resolved, provider_payload=guardrail_payload),
            db=db,
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
    except InvalidVirtualKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (AccessDeniedError, GuardrailDeniedError) as exc:
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        if resolved is not None:
            await _record_proxy_request(
                resolved=resolved,
                http_status=status.HTTP_403_FORBIDDEN,
                latency_ms=_elapsed_ms(started_at),
                usage=unknown_usage(),
                error_code="access_denied",
                db=db,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError, ProviderNotFoundError) as exc:
        await _release_reservations(reservation_ids=reservation_ids, db=db)
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
                db=db,
            )
        await _release_reservations(reservation_ids=reservation_ids, db=db)
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
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
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    authorization: str | None,
    provider_id: UUID | None,
    response_transform,
) -> Response:
    provider_payload = _to_provider_payload(body)
    raw_key = _extract_bearer_token(authorization)
    resolved = None
    reservation_ids: list[UUID] = []
    try:
        resolved = await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=raw_key,
                requested_model=provider_payload.model,
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
            db=db,
        )
        await guardrails_facade.evaluate_request(
            context=_guardrail_context(resolved=resolved, provider_payload=provider_payload),
            db=db,
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
    except InvalidVirtualKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid virtual key",
            headers={"WWW-Authenticate": "Bearer"},
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
                db=db,
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
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
                db=db,
            )
            await _release_reservations(reservation_ids=reservation_ids, db=db)
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    try:
        await guardrails_facade.evaluate_response(
            context=_guardrail_context(resolved=resolved, provider_payload=provider_payload),
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
    return JSONResponse(status_code=upstream.status_code, content=response_transform(upstream.body))


async def _stream_proxy_response(
    *,
    upstream,
    resolved,
    provider_payload: ProviderChatCompletionRequest,
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
        usage = usage_from_stream_chunks(
            request_messages=provider_payload.messages,
            chunks=chunks,
        )
        usage_cost_cents = await _record_proxy_request(
            resolved=resolved,
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


def _enforce_content_length(request: Request, max_body_bytes: int) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        body_size = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid content-length header") from exc
    if body_size > max_body_bytes:
        raise HTTPException(status_code=413, detail="request body is too large")


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
    if not isinstance(choices, list):
        return ""
    parts: list[str] = []
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
    return "\n".join(part for part in parts if part)


def _guardrail_context(
    *,
    resolved,
    provider_payload: ProviderChatCompletionRequest,
) -> GuardrailEvaluationContext:
    return GuardrailEvaluationContext(
        org_id=resolved.org_id,
        team_id=resolved.team_id,
        project_id=resolved.project_id,
        virtual_key_id=resolved.virtual_key_id,
        provider_id=resolved.provider_id,
        pool_id=resolved.pool_id,
        request_id=current_request_id(),
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
    resolved,
    http_status: int,
    latency_ms: int,
    usage: UsageAccounting,
    error_code: str | None,
    db: AsyncSession,
    provider_credential_id: UUID | None = None,
) -> int | None:
    cost_cents = _calculate_cost_cents(resolved=resolved, usage=usage)
    await usage_facade.record_usage(
        payload=RecordUsage(
            org_id=resolved.org_id,
            team_id=resolved.team_id,
            project_id=resolved.project_id,
            access_policy_id=resolved.access_policy_id,
            access_policy_route_id=resolved.access_policy_route_id,
            limit_policy_ids=[str(limit_id) for limit_id in resolved.limit_policy_ids],
            limit_policy_rule_ids=[
                str(limit.limit_policy_rule_id) for limit in resolved.limit_policies
            ],
            limit_policy_assignment_ids=[
                str(limit.limit_policy_assignment_id) for limit in resolved.limit_policies
            ],
            virtual_key_id=resolved.virtual_key_id,
            pool_id=resolved.pool_id,
            provider_id=resolved.provider_id,
            provider_credential_id=provider_credential_id or resolved.provider_key_id,
            request_id=current_request_id(),
            requested_model=resolved.requested_model,
            provider_model=resolved.provider_model,
            http_status=http_status,
            latency_ms=latency_ms,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_cents=cost_cents,
            usage_source=usage.usage_source,
            error_code=error_code,
        ),
        db=db,
    )
    return cost_cents


async def _enforce_limit_policies(
    *,
    resolved,
    estimated_input_tokens: int,
    requested_output_tokens: int | None,
    db: AsyncSession,
) -> list[UUID]:
    requested_total_tokens = estimated_input_tokens + (requested_output_tokens or 0)
    estimated_cost_cents = _calculate_cost_cents(
        resolved=resolved,
        usage=UsageAccounting(
            prompt_tokens=estimated_input_tokens,
            completion_tokens=requested_output_tokens,
            total_tokens=requested_total_tokens if requested_output_tokens is not None else None,
            usage_source="estimated",
        ),
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    for limit in resolved.limit_policies:
        if limit.limit_type == "input_tokens" and estimated_input_tokens > limit.limit_value:
            await _raise_proxy_denial(
                resolved=resolved,
                detail="limit policy input token limit exceeded",
                reason="input_token_limit",
                db=db,
            )
        if (
            limit.limit_type == "output_tokens"
            and requested_output_tokens is not None
            and requested_output_tokens > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="limit policy output token limit exceeded",
                reason="output_token_limit",
                db=db,
            )
        if limit.limit_type == "tokens_per_request" and requested_total_tokens > limit.limit_value:
            await _raise_proxy_denial(
                resolved=resolved,
                detail="limit policy request token limit exceeded",
                reason="request_token_limit",
                db=db,
            )

        since = _limit_policy_window_start(limit.interval_unit, limit.interval_count)
        (
            request_count,
            prompt_tokens,
            completion_tokens,
            cost_cents,
        ) = await usage_facade.summarize_limit_policy_usage(
            limit_policy_id=limit.limit_policy_id,
            limit_policy_rule_id=limit.limit_policy_rule_id,
            limit_policy_assignment_id=limit.limit_policy_assignment_id,
            since=since,
            db=db,
        )
        reservations = await usage_facade.summarize_active_limit_policy_reservations(
            limit_policy_id=limit.limit_policy_id,
            limit_policy_rule_id=limit.limit_policy_rule_id,
            limit_policy_assignment_id=limit.limit_policy_assignment_id,
            since=since,
            now=datetime.now(UTC),
            db=db,
        )
        if limit.limit_type == "requests" and request_count + 1 > limit.limit_value:
            await _raise_proxy_denial(
                resolved=resolved,
                detail="limit policy request limit exceeded",
                reason="request_limit",
                db=db,
            )
        if (
            limit.limit_type == "requests"
            and request_count + reservations.requests + 1 > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="limit policy request limit exceeded",
                reason="request_limit",
                db=db,
            )
        if (
            limit.limit_type == "input_tokens"
            and prompt_tokens + reservations.prompt_tokens + estimated_input_tokens
            > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="limit policy input token limit exceeded",
                reason="input_token_limit",
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
                detail="limit policy output token limit exceeded",
                reason="output_token_limit",
                db=db,
            )
        if (
            limit.limit_type == "budget_cents"
            and estimated_cost_cents is not None
            and cost_cents + reservations.cost_cents + estimated_cost_cents > limit.limit_value
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="limit policy budget exceeded",
                reason="budget_limit",
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
                detail="limit policy total token limit exceeded",
                reason="total_token_limit",
                db=db,
            )
    reservation_ids: list[UUID] = []
    for limit in resolved.limit_policies:
        reservation_ids.append(
            await usage_facade.create_limit_policy_reservation(
                payload=RecordLimitPolicyReservation(
                    org_id=resolved.org_id,
                    limit_policy_id=limit.limit_policy_id,
                    limit_policy_rule_id=limit.limit_policy_rule_id,
                    limit_policy_assignment_id=limit.limit_policy_assignment_id,
                    virtual_key_id=resolved.virtual_key_id,
                    request_id=current_request_id(),
                    reserved_prompt_tokens=estimated_input_tokens,
                    reserved_completion_tokens=requested_output_tokens or 0,
                    reserved_total_tokens=requested_total_tokens,
                    reserved_cost_cents=estimated_cost_cents,
                    expires_at=expires_at,
                ),
                db=db,
            )
        )
    await db.commit()
    return reservation_ids


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


async def _raise_proxy_denial(
    *,
    resolved,
    detail: str,
    reason: str,
    db: AsyncSession,
) -> None:
    await _record_proxy_activity(
        resolved=resolved,
        action="proxy.denied",
        message=detail,
        severity="warning",
        metadata={"reason": reason},
        db=db,
    )
    raise HTTPException(status_code=403, detail=detail)


async def _record_proxy_activity(
    *,
    resolved,
    action: str,
    message: str,
    severity: str,
    metadata: dict,
    db: AsyncSession,
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
        return now - timedelta(days=30 * interval_count)
    return None


def _calculate_cost_cents(*, resolved, usage: UsageAccounting) -> int | None:
    return default_cost_calculator_registry.calculate_cents(
        context=CostingContext(
            provider_id=str(resolved.provider_id),
            provider_model=resolved.provider_model,
            input_price_per_million_tokens=resolved.input_price_per_million_tokens,
            output_price_per_million_tokens=resolved.output_price_per_million_tokens,
        ),
        usage=usage,
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
