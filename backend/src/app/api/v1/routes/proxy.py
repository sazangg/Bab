import json
import math
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
from app.modules.usage import facade as usage_facade
from app.modules.usage.accounting import (
    UsageAccounting,
    estimate_request_tokens,
    unknown_usage,
    usage_from_provider_response,
    usage_from_stream_chunks,
)
from app.modules.usage.schemas import RecordUsage

router = APIRouter(prefix="/v1", tags=["proxy"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
VirtualKeyAuthorization = Annotated[str | None, Header(alias="Authorization")]
ProviderIdHeader = Annotated[UUID | None, Header(alias="X-Bab-Provider-Id")]


async def get_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        yield client


ProxyHttpClient = Annotated[httpx.AsyncClient, Depends(get_proxy_http_client)]


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    request: Request,
    db: DatabaseSession,
    http_client: ProxyHttpClient,
    authorization: VirtualKeyAuthorization = None,
    provider_id: ProviderIdHeader = None,
) -> Response:
    started_at = perf_counter()
    _enforce_content_length(request)
    raw_body = await request.body()
    _enforce_body_size(raw_body)
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
        db=db,
    )
    return JSONResponse(status_code=upstream.status_code, content=upstream.body)


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
            db=db,
        )


def _enforce_content_length(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        body_size = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid content-length header") from exc
    if body_size > settings.proxy_max_body_bytes:
        raise HTTPException(status_code=413, detail="request body is too large")


def _enforce_body_size(raw_body: bytes) -> None:
    if len(raw_body) > settings.proxy_max_body_bytes:
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
                provider_credential_id=resolved.provider_key_id,
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
    if usage.prompt_tokens is None and usage.completion_tokens is None:
        return None
    input_price = resolved.input_price_per_million_tokens
    output_price = resolved.output_price_per_million_tokens
    if input_price is None and output_price is None:
        return None
    input_cost = (usage.prompt_tokens or 0) * (input_price or 0)
    output_cost = (usage.completion_tokens or 0) * (output_price or 0)
    total_cost = input_cost + output_cost
    if total_cost <= 0:
        return 0
    return math.ceil(total_cost / 1_000_000)


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
