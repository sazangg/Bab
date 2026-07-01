import httpcore
import httpx
import pytest

from app.core import provider_http


class _FakeDelegate:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def connect_tcp(self, host, port, **kwargs):
        self.calls.append((host, port))
        return object()


@pytest.mark.asyncio
async def test_validating_network_backend_connects_to_validated_ip(monkeypatch) -> None:
    async def resolve(host: str) -> list[str]:
        assert host == "api.provider.test"
        return ["93.184.216.34"]

    delegate = _FakeDelegate()
    backend = provider_http.ValidatingNetworkBackend(allow_private_provider_urls=False)
    backend._delegate = delegate
    monkeypatch.setattr(provider_http, "resolve_public_addresses", resolve)

    await backend.connect_tcp("api.provider.test", 443)

    assert delegate.calls == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_validating_network_backend_blocks_rebound_private_answer(monkeypatch) -> None:
    async def resolve(_host: str) -> list[str]:
        return ["127.0.0.1"]

    delegate = _FakeDelegate()
    backend = provider_http.ValidatingNetworkBackend(allow_private_provider_urls=False)
    backend._delegate = delegate
    monkeypatch.setattr(provider_http, "resolve_public_addresses", resolve)

    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("api.provider.test", 443)

    assert delegate.calls == []


@pytest.mark.asyncio
async def test_validating_network_backend_preserves_private_opt_in() -> None:
    delegate = _FakeDelegate()
    backend = provider_http.ValidatingNetworkBackend(allow_private_provider_urls=True)
    backend._delegate = delegate

    await backend.connect_tcp("127.0.0.1", 11434)

    assert delegate.calls == [("127.0.0.1", 11434)]


def test_provider_async_client_uses_safe_transport_defaults() -> None:
    client = provider_http.provider_async_client(timeout=30)

    assert isinstance(client._transport, provider_http.ProviderAsyncHTTPTransport)
    assert client.follow_redirects is False
    assert isinstance(client, httpx.AsyncClient)
