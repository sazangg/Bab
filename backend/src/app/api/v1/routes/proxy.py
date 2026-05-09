import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import Scope, get_db
from app.modules.keys import facade as keys_facade
from app.modules.keys.errors import AccessDeniedError, InvalidVirtualKeyError
from app.modules.keys.schemas import ResolveAccessRequest
from app.modules.providers import facade as providers_facade
from app.modules.providers.errors import (
    ProviderAdapterNotFoundError,
    ProviderInactiveError,
    ProviderUpstreamError,
)
from app.modules.providers.schemas import ProviderChatCompletionRequest

router = APIRouter(prefix="/v1", tags=["proxy"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
VirtualKeyAuthorization = Annotated[str | None, Header(alias="Authorization")]
ProviderIdHeader = Annotated[UUID | None, Header(alias="X-Bab-Provider-Id")]


async def get_proxy_http_client() -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        yield client


ProxyHttpClient = Annotated[httpx.AsyncClient, Depends(get_proxy_http_client)]


@router.post("/chat/completions")
async def create_chat_completion(
    request: Request,
    db: DatabaseSession,
    http_client: ProxyHttpClient,
    authorization: VirtualKeyAuthorization = None,
    provider_id: ProviderIdHeader = None,
) -> JSONResponse:
    _enforce_content_length(request)
    raw_body = await request.body()
    _enforce_body_size(raw_body)
    body = _decode_json_body(raw_body)
    if body.get("stream") is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="streaming chat completions are not supported yet",
        )

    provider_payload = _to_provider_payload(body)
    raw_key = _extract_bearer_token(authorization)
    try:
        resolved = await keys_facade.resolve_access(
            payload=ResolveAccessRequest(
                raw_key=raw_key,
                requested_model=provider_payload.model,
                provider_id=provider_id,
            ),
            db=db,
        )
        upstream = await providers_facade.create_chat_completion(
            provider_id=resolved.provider_id,
            payload=ProviderChatCompletionRequest(
                model=resolved.provider_model,
                messages=provider_payload.messages,
                extra_body=provider_payload.extra_body,
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="model or provider is not allowed for this key",
        ) from exc
    except (ProviderInactiveError, ProviderAdapterNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider is not available",
        ) from exc
    except ProviderUpstreamError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.body)

    return JSONResponse(status_code=upstream.status_code, content=upstream.body)


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
