from dataclasses import dataclass
from typing import Protocol

import httpx

from app.modules.providers.errors import ProviderAdapterNotFoundError, ProviderUpstreamError
from app.modules.providers.schemas import (
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
)

OPENAI_COMPAT_ADAPTER = "openai_compat"


@dataclass(frozen=True)
class AdapterProvider:
    base_url: str
    api_key: str


class ProviderAdapter(Protocol):
    async def list_models(
        self,
        *,
        provider: AdapterProvider,
        http_client: httpx.AsyncClient,
    ) -> list[str]:
        pass

    async def create_chat_completion(
        self,
        *,
        provider: AdapterProvider,
        payload: ProviderChatCompletionRequest,
        http_client: httpx.AsyncClient,
    ) -> ProviderChatCompletionResponse:
        pass

    async def stream_chat_completion(
        self,
        *,
        provider: AdapterProvider,
        payload: ProviderChatCompletionRequest,
        http_client: httpx.AsyncClient,
    ) -> ProviderChatCompletionStream:
        pass


class OpenAICompatibleAdapter:
    async def list_models(
        self,
        *,
        provider: AdapterProvider,
        http_client: httpx.AsyncClient,
    ) -> list[str]:
        response = await http_client.get(
            f"{provider.base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {provider.api_key}"},
        )
        body = _response_body(response)
        if response.is_error:
            raise ProviderUpstreamError(status_code=response.status_code, body=body)
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise ProviderUpstreamError(status_code=response.status_code, body=body)

        model_ids = []
        for item in body["data"]:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                model_ids.append(item["id"])
        return model_ids

    async def create_chat_completion(
        self,
        *,
        provider: AdapterProvider,
        payload: ProviderChatCompletionRequest,
        http_client: httpx.AsyncClient,
    ) -> ProviderChatCompletionResponse:
        response = await http_client.post(
            f"{provider.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {provider.api_key}"},
            json=_to_openai_body(payload),
        )
        body = _response_body(response)
        if response.is_error:
            raise ProviderUpstreamError(status_code=response.status_code, body=body)
        if not isinstance(body, dict):
            raise ProviderUpstreamError(status_code=response.status_code, body=body)
        return ProviderChatCompletionResponse(status_code=response.status_code, body=body)

    async def stream_chat_completion(
        self,
        *,
        provider: AdapterProvider,
        payload: ProviderChatCompletionRequest,
        http_client: httpx.AsyncClient,
    ) -> ProviderChatCompletionStream:
        request = http_client.build_request(
            "POST",
            f"{provider.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {provider.api_key}"},
            json=_to_openai_body(payload),
        )
        response = await http_client.send(request, stream=True)
        if response.is_error:
            content = await response.aread()
            await response.aclose()
            body = _response_body_from_content(response, content)
            raise ProviderUpstreamError(status_code=response.status_code, body=body)

        return ProviderChatCompletionStream(
            status_code=response.status_code,
            chunks=response.aiter_bytes(),
            close=response.aclose,
            media_type=response.headers.get("content-type", "text/event-stream"),
        )


class ProviderAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter_type: str, adapter: ProviderAdapter) -> None:
        self._adapters[adapter_type] = adapter

    def get(self, adapter_type: str) -> ProviderAdapter:
        adapter = self._adapters.get(adapter_type)
        if adapter is None:
            raise ProviderAdapterNotFoundError
        return adapter


def create_default_adapter_registry() -> ProviderAdapterRegistry:
    registry = ProviderAdapterRegistry()
    registry.register(OPENAI_COMPAT_ADAPTER, OpenAICompatibleAdapter())
    return registry


default_adapter_registry = create_default_adapter_registry()


def _to_openai_body(payload: ProviderChatCompletionRequest) -> dict:
    return {
        **payload.extra_body,
        "model": payload.model,
        "messages": payload.messages,
    }


def _response_body(response: httpx.Response) -> dict | list | str | None:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def _response_body_from_content(
    response: httpx.Response, content: bytes
) -> dict | list | str | None:
    if not content:
        return None
    try:
        return response.json()
    except ValueError:
        return content.decode(errors="replace")
