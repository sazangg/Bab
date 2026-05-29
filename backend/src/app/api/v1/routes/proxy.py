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
from app.modules.providers.schemas import ProviderChatCompletionRequest
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
from app.modules.usage.schemas import RecordUsage

router = APIRouter(prefix="/v1", tags=["proxy"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
VirtualKeyAuthorization = Annotated[str | None, Header(alias="Authorization")]
ProviderIdHeader = Annotated[UUID | None, Header(alias="X-Bab-Provider-Id")]


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
            detail="no active allocation",
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
        await _enforce_allocation_limits(
            resolved=resolved,
            estimated_input_tokens=estimated_tokens,
            requested_output_tokens=_requested_output_tokens(provider_payload.extra_body),
            db=db,
        )
        await guardrails_facade.evaluate_request(
            context=GuardrailEvaluationContext(
                org_id=resolved.org_id,
                team_id=resolved.team_id,
                project_id=resolved.project_id,
                allocation_id=resolved.allocation_id,
                allocation_chain_ids=resolved.allocation_chain_ids,
                virtual_key_id=resolved.virtual_key_id,
                provider_id=resolved.provider_id,
                pool_id=resolved.pool_id,
                requested_model=resolved.requested_model,
                provider_model=resolved.provider_model,
                prompt_text=_messages_text(provider_payload.messages),
            ),
            db=db,
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
        if resolved is not None:
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.denied",
                message="Proxy request denied by allocation or provider routing policy.",
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

    await _record_proxy_request(
        resolved=resolved,
        http_status=upstream.status_code,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        error_code=None,
        provider_credential_id=upstream.provider_credential_id,
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
        await _enforce_allocation_limits(
            resolved=resolved,
            estimated_input_tokens=estimated_tokens,
            requested_output_tokens=_requested_output_tokens(provider_payload.extra_body),
            db=db,
        )
        await guardrails_facade.evaluate_request(
            context=GuardrailEvaluationContext(
                org_id=resolved.org_id,
                team_id=resolved.team_id,
                project_id=resolved.project_id,
                allocation_id=resolved.allocation_id,
                allocation_chain_ids=resolved.allocation_chain_ids,
                virtual_key_id=resolved.virtual_key_id,
                provider_id=resolved.provider_id,
                pool_id=resolved.pool_id,
                requested_model=resolved.requested_model,
                provider_model=resolved.provider_model,
                prompt_text=_messages_text(provider_payload.messages),
            ),
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
        if resolved is not None:
            await _record_proxy_activity(
                resolved=resolved,
                action="proxy.denied",
                message="Proxy request denied by allocation or provider routing policy.",
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
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    usage = usage_from_provider_response(
        request_messages=provider_payload.messages,
        response_body=upstream.body,
    )
    await _record_proxy_request(
        resolved=resolved,
        http_status=upstream.status_code,
        latency_ms=_elapsed_ms(started_at),
        usage=usage,
        error_code=None,
        provider_credential_id=upstream.provider_credential_id,
        db=db,
    )
    return JSONResponse(status_code=upstream.status_code, content=response_transform(upstream.body))


async def _stream_proxy_response(
    *,
    upstream,
    resolved,
    provider_payload: ProviderChatCompletionRequest,
    estimated_tokens: int,
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
        await _record_proxy_request(
            resolved=resolved,
            http_status=upstream.status_code,
            latency_ms=_elapsed_ms(started_at),
            usage=usage,
            error_code=error_code,
            provider_credential_id=upstream.provider_credential_id,
            db=db,
        )


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


def _messages_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        parts.append(_content_to_text(message.get("content")))
    return "\n".join(parts)


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


async def _record_proxy_request(
    *,
    resolved,
    http_status: int,
    latency_ms: int,
    usage: UsageAccounting,
    error_code: str | None,
    db: AsyncSession,
    provider_credential_id: UUID | None = None,
) -> None:
    for allocation_id in resolved.allocation_chain_ids:
        await usage_facade.record_usage(
            payload=RecordUsage(
                org_id=resolved.org_id,
                team_id=resolved.team_id,
                project_id=resolved.project_id,
                allocation_id=allocation_id,
                virtual_key_id=resolved.virtual_key_id,
                pool_id=resolved.pool_id,
                provider_id=resolved.provider_id,
                provider_credential_id=provider_credential_id or resolved.provider_key_id,
                requested_model=resolved.requested_model,
                provider_model=resolved.provider_model,
                http_status=http_status,
                latency_ms=latency_ms,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cost_cents=_calculate_cost_cents(resolved=resolved, usage=usage),
                usage_source=usage.usage_source,
                error_code=error_code,
            ),
            db=db,
        )


async def _enforce_allocation_limits(
    *,
    resolved,
    estimated_input_tokens: int,
    requested_output_tokens: int | None,
    db: AsyncSession,
) -> None:
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
    for limit in resolved.allocation_limits:
        if limit.max_input_tokens is not None and estimated_input_tokens > limit.max_input_tokens:
            await _raise_proxy_denial(
                resolved=resolved,
                detail="allocation input token limit exceeded",
                reason="input_token_limit",
                db=db,
            )
        if (
            limit.max_output_tokens is not None
            and requested_output_tokens is not None
            and requested_output_tokens > limit.max_output_tokens
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="allocation output token limit exceeded",
                reason="output_token_limit",
                db=db,
            )
        if (
            limit.max_tokens_per_request is not None
            and requested_total_tokens > limit.max_tokens_per_request
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="allocation request token limit exceeded",
                reason="request_token_limit",
                db=db,
            )

        since = _allocation_window_start(limit.window)
        (
            request_count,
            prompt_tokens,
            completion_tokens,
            cost_cents,
        ) = await usage_facade.summarize_allocation_usage(
            allocation_id=limit.allocation_id,
            since=since,
            db=db,
        )
        if limit.max_requests is not None and request_count + 1 > limit.max_requests:
            await _raise_proxy_denial(
                resolved=resolved,
                detail="allocation request limit exceeded",
                reason="request_limit",
                db=db,
            )
        if (
            limit.max_input_tokens is not None
            and prompt_tokens + estimated_input_tokens > limit.max_input_tokens
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="allocation input token limit exceeded",
                reason="input_token_limit",
                db=db,
            )
        if (
            limit.max_output_tokens is not None
            and requested_output_tokens is not None
            and completion_tokens + requested_output_tokens > limit.max_output_tokens
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="allocation output token limit exceeded",
                reason="output_token_limit",
                db=db,
            )
        if (
            limit.budget_cents is not None
            and estimated_cost_cents is not None
            and cost_cents + estimated_cost_cents > limit.budget_cents
        ):
            await _raise_proxy_denial(
                resolved=resolved,
                detail="allocation budget exceeded",
                reason="budget_limit",
                db=db,
            )


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
            allocation_id=resolved.allocation_id,
            virtual_key_id=resolved.virtual_key_id,
            provider_id=resolved.provider_id,
            pool_id=resolved.pool_id,
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


def _allocation_window_start(window: str) -> datetime | None:
    now = datetime.now(UTC)
    if window == "daily":
        return now - timedelta(days=1)
    if window == "weekly":
        return now - timedelta(weeks=1)
    if window == "monthly":
        return now - timedelta(days=30)
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
