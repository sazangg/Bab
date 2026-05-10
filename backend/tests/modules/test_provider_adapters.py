import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.core.security import encrypt
from app.modules.auth.internal.models import Organization
from app.modules.providers.errors import (
    ProviderAdapterNotFoundError,
    ProviderInactiveError,
    ProviderUpstreamError,
)
from app.modules.providers.facade import create_chat_completion
from app.modules.providers.internal.adapters import (
    AdapterProvider,
    OpenAICompatibleAdapter,
    ProviderAdapterRegistry,
)
from app.modules.providers.internal.models import Provider
from app.modules.providers.schemas import ProviderChatCompletionRequest


@pytest.mark.asyncio
async def test_openai_compatible_adapter_posts_chat_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer provider-secret"
        assert request.read()
        return httpx.Response(
            200,
            json={"id": "chatcmpl_123", "choices": [{"message": {"content": "hello"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await OpenAICompatibleAdapter().create_chat_completion(
            provider=AdapterProvider(
                base_url="https://api.example.test/v1",
                api_key="provider-secret",
            ),
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
                extra_body={"temperature": 0.2},
            ),
            http_client=http_client,
        )

    assert response.status_code == 200
    assert response.body["id"] == "chatcmpl_123"


@pytest.mark.asyncio
async def test_openai_compatible_adapter_raises_for_upstream_error() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, json={"error": "limited"}))
    ) as http_client:
        with pytest.raises(ProviderUpstreamError) as exc_info:
            await OpenAICompatibleAdapter().create_chat_completion(
                provider=AdapterProvider(
                    base_url="https://api.example.test/v1",
                    api_key="provider-secret",
                ),
                payload=ProviderChatCompletionRequest(
                    model="gpt-5.4-mini",
                    messages=[{"role": "user", "content": "Hello"}],
                ),
                http_client=http_client,
            )

    assert exc_info.value.status_code == 429
    assert exc_info.value.body == {"error": "limited"}


@pytest.mark.asyncio
async def test_openai_compatible_adapter_streams_chat_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer provider-secret"
        assert b'"stream":true' in request.read()
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=httpx.ByteStream(
                b"".join(
                    [
                        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n',
                        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
                        b"data: [DONE]\n\n",
                    ]
                )
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await OpenAICompatibleAdapter().stream_chat_completion(
            provider=AdapterProvider(
                base_url="https://api.example.test/v1",
                api_key="provider-secret",
            ),
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
                extra_body={"stream": True},
            ),
            http_client=http_client,
        )
        chunks = [chunk async for chunk in response.chunks]
        await response.close()

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert b"".join(chunks) == (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )


def test_registry_rejects_unknown_adapter_type() -> None:
    with pytest.raises(ProviderAdapterNotFoundError):
        ProviderAdapterRegistry().get("missing")


@pytest.mark.asyncio
async def test_provider_facade_decrypts_secret_and_uses_adapter(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Provider Org", slug="provider-adapter-org")
    db_session.add(org)
    await db_session.flush()
    provider = Provider(
        org_id=org.id,
        name="OpenAI",
        base_url="https://api.example.test/v1",
        api_key_encrypted=encrypt("provider-secret"),
        adapter_type="openai_compat",
    )
    db_session.add(provider)
    await db_session.commit()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer provider-secret"
        return httpx.Response(200, json={"id": "chatcmpl_123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": "Hello"}],
            ),
            scope=Scope(org_id=org.id),
            db=db_session,
            http_client=http_client,
        )

    assert response.body == {"id": "chatcmpl_123"}


@pytest.mark.asyncio
async def test_provider_facade_rejects_inactive_provider(db_session: AsyncSession) -> None:
    org = Organization(name="Provider Org", slug="inactive-provider-adapter-org")
    db_session.add(org)
    await db_session.flush()
    provider = Provider(
        org_id=org.id,
        name="OpenAI",
        base_url="https://api.example.test/v1",
        api_key_encrypted=encrypt("provider-secret"),
        adapter_type="openai_compat",
        is_active=False,
    )
    db_session.add(provider)
    await db_session.commit()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        with pytest.raises(ProviderInactiveError):
            await create_chat_completion(
                provider_id=provider.id,
                payload=ProviderChatCompletionRequest(
                    model="gpt-5.4-mini",
                    messages=[{"role": "user", "content": "Hello"}],
                ),
                scope=Scope(org_id=org.id),
                db=db_session,
                http_client=client,
            )
