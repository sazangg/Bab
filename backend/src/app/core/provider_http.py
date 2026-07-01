from collections.abc import AsyncIterable, Iterable

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from httpx._transports.default import AsyncResponseStream, map_httpcore_exceptions

from app.core.config import settings
from app.core.ssrf import SsrfValidationError, _is_disallowed_ip, resolve_public_addresses


class ValidatingNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, *, allow_private_provider_urls: bool | None = None) -> None:
        self._delegate = AutoBackend()
        self._allow_private_provider_urls = (
            settings.allow_private_provider_urls
            if allow_private_provider_urls is None
            else allow_private_provider_urls
        )

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if self._allow_private_provider_urls:
            return await self._delegate.connect_tcp(
                host,
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )
        try:
            selected_address = (await resolve_public_addresses(host))[0]
            if _is_disallowed_ip(selected_address):
                raise SsrfValidationError("host resolves to a non-public address")
        except SsrfValidationError as exc:
            raise httpcore.ConnectError("provider destination is not allowed") from exc
        return await self._delegate.connect_tcp(
            selected_address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("unix sockets are not allowed for provider traffic")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class ProviderAsyncHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=ValidatingNetworkBackend(),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.AsyncByteStream)
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        with map_httpcore_exceptions():
            core_response = await self._pool.handle_async_request(core_request)
        assert isinstance(core_response.stream, AsyncIterable)
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=AsyncResponseStream(core_response.stream),
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def provider_async_client(*, timeout: httpx.Timeout | float | int) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        transport=ProviderAsyncHTTPTransport(),
        follow_redirects=False,
        trust_env=False,
    )
