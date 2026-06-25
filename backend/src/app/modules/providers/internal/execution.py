import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Scope
from app.modules.providers.errors import (
    ProviderAdapterNotFoundError,
    ProviderCredentialRequiredError,
    ProviderInactiveError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.internal import credential_routing, repository
from app.modules.providers.internal.adapters import (
    AdapterProvider,
    anthropic_messages_adapter,
    default_adapter_registry,
)
from app.modules.providers.internal.models import Provider, ProviderCredential
from app.modules.providers.internal.secret_backends import ProviderSecretBackendRegistry
from app.modules.providers.schemas import (
    ProviderAnthropicMessagesRequest,
    ProviderAnthropicMessagesResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
    ProviderOperationalState,
)
from app.modules.settings import facade as settings_facade

_provider_semaphores: dict[UUID, tuple[int, asyncio.Semaphore]] = {}
_provider_circuit_events: dict[UUID, deque[tuple[datetime, bool]]] = defaultdict(deque)
_provider_circuit_open_until: dict[UUID, datetime] = {}


async def create_chat_completion(
    *,
    provider_id: UUID,
    pool_id: UUID | None = None,
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderChatCompletionResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    request_timeout_seconds = (
        provider.request_timeout_seconds or org_settings.default_request_timeout_seconds
    )
    retry_policy = _retry_policy(
        provider,
        default_retry_count=org_settings.default_retry_count,
    )

    _raise_if_circuit_open(provider)
    adapter = default_adapter_registry.get(provider.adapter_type)
    routed_credentials = await credential_routing.resolve_provider_credential_route(
        provider=provider,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    last_error: ProviderUpstreamError | None = None
    async with _provider_concurrency_slot(provider):
        for credential in routed_credentials:

            async def call_upstream(
                routed_credential: ProviderCredential | None = credential,
            ) -> ProviderChatCompletionResponse:
                return await adapter.create_chat_completion(
                    provider=AdapterProvider(
                        base_url=provider.base_url,
                        api_key=await credential_routing.api_key_for_routed_credential(
                            provider=provider,
                            credential=routed_credential,
                            secret_registry=secret_registry,
                        ),
                    ),
                    payload=payload,
                    http_client=http_client,
                )

            try:
                response = await _call_with_retries(
                    call=call_upstream,
                    request_timeout_seconds=request_timeout_seconds,
                    retry_policy=retry_policy,
                )
                _record_circuit_success(provider)
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                    response.provider_credential_id = credential.id
                return response
            except ProviderUpstreamError as exc:
                last_error = exc
                _record_circuit_failure(provider)
                if credential is not None:
                    await credential_routing.mark_provider_credential_failed(
                        provider_credential=credential,
                        error=exc,
                        db=db,
                    )
                if (
                    provider_credential_id is not None
                    or not credential_routing.should_try_next_credential(exc)
                ):
                    break

    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


async def create_anthropic_message(
    *,
    provider_id: UUID,
    pool_id: UUID | None,
    provider_credential_id: UUID | None,
    payload: ProviderAnthropicMessagesRequest,
    anthropic_version: str,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderAnthropicMessagesResponse:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError
    if provider.supported_integration != "anthropic_messages":
        raise ProviderAdapterNotFoundError

    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    request_timeout_seconds = (
        provider.request_timeout_seconds or org_settings.default_request_timeout_seconds
    )
    retry_policy = _retry_policy(provider, default_retry_count=org_settings.default_retry_count)
    _raise_if_circuit_open(provider)
    routed_credentials = await credential_routing.resolve_provider_credential_route(
        provider=provider,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    last_error: ProviderUpstreamError | None = None
    async with _provider_concurrency_slot(provider):
        for credential in routed_credentials:

            async def call_upstream(
                routed_credential: ProviderCredential | None = credential,
            ) -> ProviderAnthropicMessagesResponse:
                return await anthropic_messages_adapter.create_message(
                    provider=AdapterProvider(
                        base_url=provider.base_url,
                        api_key=await credential_routing.api_key_for_routed_credential(
                            provider=provider,
                            credential=routed_credential,
                            secret_registry=secret_registry,
                        ),
                    ),
                    payload=payload,
                    anthropic_version=anthropic_version,
                    http_client=http_client,
                )

            try:
                response = await _call_with_retries(
                    call=call_upstream,
                    request_timeout_seconds=request_timeout_seconds,
                    retry_policy=retry_policy,
                )
                _record_circuit_success(provider)
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                    response.provider_credential_id = credential.id
                return response
            except ProviderUpstreamError as exc:
                last_error = exc
                _record_circuit_failure(provider)
                if credential is not None:
                    await credential_routing.mark_provider_credential_failed(
                        provider_credential=credential,
                        error=exc,
                        db=db,
                    )
                if (
                    provider_credential_id is not None
                    or not credential_routing.should_try_next_credential(exc)
                ):
                    break

    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


async def stream_chat_completion(
    *,
    provider_id: UUID,
    pool_id: UUID | None = None,
    provider_credential_id: UUID | None = None,
    payload: ProviderChatCompletionRequest,
    scope: Scope,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None = None,
) -> ProviderChatCompletionStream:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    request_timeout_seconds = (
        provider.request_timeout_seconds or org_settings.default_request_timeout_seconds
    )

    adapter = default_adapter_registry.get(provider.adapter_type)
    routed_credentials = await credential_routing.resolve_provider_credential_route(
        provider=provider,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    last_error: ProviderUpstreamError | None = None
    _raise_if_circuit_open(provider)
    concurrency_slot = _provider_concurrency_slot(provider)
    await concurrency_slot.__aenter__()
    stream_returned = False
    try:
        for credential in routed_credentials:
            try:
                async with asyncio.timeout(request_timeout_seconds):
                    stream = await adapter.stream_chat_completion(
                        provider=AdapterProvider(
                            base_url=provider.base_url,
                            api_key=await credential_routing.api_key_for_routed_credential(
                                provider=provider,
                                credential=credential,
                                secret_registry=secret_registry,
                            ),
                        ),
                        payload=payload,
                        http_client=http_client,
                    )
                if credential is not None:
                    await repository.mark_provider_credential_used(
                        provider_credential=credential,
                        db=db,
                    )
                    stream.provider_credential_id = credential.id
                original_chunks = stream.chunks
                original_close = stream.close
                released = False

                async def release_stream(
                    close_stream: Callable[[], Awaitable[None]] = original_close,
                ) -> None:
                    nonlocal released
                    if released:
                        return
                    released = True
                    await close_stream()
                    await concurrency_slot.__aexit__(None, None, None)

                async def managed_chunks(
                    chunks: AsyncIterator[bytes] = original_chunks,
                    routed_credential=credential,
                ) -> AsyncIterator[bytes]:
                    try:
                        async for chunk in chunks:
                            yield chunk
                    except Exception as exc:
                        error = (
                            exc
                            if isinstance(exc, ProviderUpstreamError)
                            else ProviderUpstreamError(
                                status_code=502,
                                body={"error": "provider stream failed"},
                                failure_reason="stream_failed",
                            )
                        )
                        _record_circuit_failure(provider)
                        if routed_credential is not None:
                            await credential_routing.mark_provider_credential_failed(
                                provider_credential=routed_credential,
                                error=error,
                                db=db,
                            )
                        raise
                    else:
                        _record_circuit_success(provider)
                    finally:
                        await release_stream()

                stream.chunks = managed_chunks()
                stream.close = release_stream
                stream_returned = True
                return stream
            except TimeoutError as exc:
                last_error = ProviderUpstreamError(
                    status_code=504,
                    body={"error": "provider request timed out"},
                    failure_reason="timeout",
                )
                _record_circuit_failure(provider)
                if credential is not None:
                    await credential_routing.mark_provider_credential_failed(
                        provider_credential=credential,
                        error=last_error,
                        db=db,
                    )
                if provider_credential_id is not None:
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = ProviderUpstreamError(
                    status_code=502,
                    body={"error": "provider upstream connection failed"},
                    failure_reason="connection_failed",
                )
                _record_circuit_failure(provider)
                if credential is not None:
                    await credential_routing.mark_provider_credential_failed(
                        provider_credential=credential,
                        error=last_error,
                        db=db,
                    )
                if provider_credential_id is not None:
                    raise last_error from exc
            except ProviderUpstreamError as exc:
                last_error = exc
                _record_circuit_failure(provider)
                if credential is not None:
                    await credential_routing.mark_provider_credential_failed(
                        provider_credential=credential,
                        error=exc,
                        db=db,
                    )
                if (
                    provider_credential_id is not None
                    or not credential_routing.should_try_next_credential(exc)
                ):
                    raise
        if last_error is not None:
            raise last_error
        raise ProviderCredentialRequiredError
    finally:
        if not stream_returned:
            await concurrency_slot.__aexit__(None, None, None)


def provider_operational_state(provider: Provider) -> ProviderOperationalState:
    circuit_policy = _circuit_breaker_policy(provider)
    events = list(_provider_circuit_events.get(provider.id, []))
    open_until = _provider_circuit_open_until.get(provider.id)
    if open_until is not None and open_until <= datetime.now(UTC):
        open_until = None
    return ProviderOperationalState(
        circuit_breaker_enabled=circuit_policy["enabled"],
        circuit_state="open" if open_until is not None else "closed",
        circuit_open_until=open_until,
        recent_circuit_failures=sum(1 for _created_at, succeeded in events if not succeeded),
        recent_circuit_successes=sum(1 for _created_at, succeeded in events if succeeded),
    )


async def _call_with_retries(
    *,
    call: Callable[[], Awaitable[Any]],
    request_timeout_seconds: int,
    retry_policy: dict,
) -> Any:
    max_attempts = retry_policy["max_attempts"] if retry_policy["enabled"] else 1
    last_error: ProviderUpstreamError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with asyncio.timeout(request_timeout_seconds):
                return await call()
        except TimeoutError as exc:
            # A client-side timeout leaves the upstream state unknown. Both callers are
            # non-idempotent completion POSTs, so replaying could double-execute (and
            # double-bill); a timeout is never retried regardless of retry_on_status.
            raise ProviderUpstreamError(
                status_code=504,
                body={"error": "provider request timed out"},
                failure_reason="timeout",
            ) from exc
        except httpx.RequestError as exc:
            last_error = ProviderUpstreamError(
                status_code=502,
                body={"error": "provider upstream connection failed"},
                failure_reason="connection_failed",
            )
            if attempt >= max_attempts or 502 not in retry_policy["retry_on_status"]:
                raise last_error from exc
        except ProviderUpstreamError as exc:
            last_error = exc
            if attempt >= max_attempts or exc.status_code not in retry_policy["retry_on_status"]:
                raise
        await asyncio.sleep(_retry_delay_seconds(retry_policy, attempt))
    if last_error is not None:
        raise last_error
    raise ProviderCredentialRequiredError


def _retry_delay_seconds(policy: dict, attempt: int) -> float:
    initial = policy["initial_delay_ms"] / 1000
    maximum = policy["max_delay_ms"] / 1000
    if policy["backoff"] == "constant":
        return min(initial, maximum)
    if policy["backoff"] == "linear":
        return min(initial * attempt, maximum)
    return min(initial * (2 ** (attempt - 1)), maximum)


def _retry_policy(provider: Provider, *, default_retry_count: int = 0) -> dict:
    stored = provider.retry_policy if isinstance(provider.retry_policy, dict) else {}
    inherited_enabled = default_retry_count > 0
    inherited_attempts = max(1, min(default_retry_count + 1, 10))
    return {
        "enabled": bool(stored.get("enabled", inherited_enabled)),
        "max_attempts": _int_policy_value(
            stored.get("max_attempts"),
            inherited_attempts,
            minimum=1,
            maximum=10,
        ),
        "backoff": (
            stored.get("backoff")
            if stored.get("backoff") in {"constant", "linear", "exponential"}
            else "exponential"
        ),
        "initial_delay_ms": _int_policy_value(
            stored.get("initial_delay_ms"),
            500,
            minimum=0,
        ),
        "max_delay_ms": _int_policy_value(stored.get("max_delay_ms"), 10000, minimum=0),
        "retry_on_status": _status_policy_values(
            stored.get("retry_on_status"),
            fallback={408, 429, 500, 502, 503, 504},
        ),
    }


def _circuit_breaker_policy(provider: Provider) -> dict:
    stored = (
        provider.circuit_breaker_policy if isinstance(provider.circuit_breaker_policy, dict) else {}
    )
    return {
        "enabled": bool(stored.get("enabled", False)),
        "failure_threshold_pct": _int_policy_value(
            stored.get("failure_threshold_pct"),
            50,
            minimum=0,
            maximum=100,
        ),
        "min_request_count": _int_policy_value(stored.get("min_request_count"), 20, minimum=0),
        "window_seconds": _int_policy_value(stored.get("window_seconds"), 60, minimum=1),
        "cooldown_seconds": _int_policy_value(stored.get("cooldown_seconds"), 30, minimum=1),
    }


def _raise_if_circuit_open(provider: Provider) -> None:
    policy = _circuit_breaker_policy(provider)
    if not policy["enabled"]:
        return
    now = datetime.now(UTC)
    open_until = _provider_circuit_open_until.get(provider.id)
    if open_until and open_until > now:
        raise ProviderUpstreamError(
            status_code=503,
            body={"error": "provider circuit is open"},
            failure_reason="circuit_open",
        )
    if open_until:
        _provider_circuit_open_until.pop(provider.id, None)


def _record_circuit_success(provider: Provider) -> None:
    policy = _circuit_breaker_policy(provider)
    if not policy["enabled"]:
        return
    _record_circuit_event(provider, succeeded=True, policy=policy)
    _provider_circuit_open_until.pop(provider.id, None)


def _record_circuit_failure(provider: Provider) -> None:
    policy = _circuit_breaker_policy(provider)
    if not policy["enabled"]:
        return
    now = datetime.now(UTC)
    events = _record_circuit_event(provider, succeeded=False, policy=policy, now=now)
    if len(events) < policy["min_request_count"]:
        return
    failure_count = sum(1 for _, succeeded in events if not succeeded)
    failure_pct = int((failure_count / len(events)) * 100)
    if failure_pct < policy["failure_threshold_pct"]:
        return
    _provider_circuit_open_until[provider.id] = now + timedelta(
        seconds=policy["cooldown_seconds"],
    )


def _record_circuit_event(
    provider: Provider,
    *,
    succeeded: bool,
    policy: dict,
    now: datetime | None = None,
) -> deque[tuple[datetime, bool]]:
    recorded_at = now or datetime.now(UTC)
    events = _provider_circuit_events[provider.id]
    events.append((recorded_at, succeeded))
    window_started_at = recorded_at.timestamp() - policy["window_seconds"]
    while events and events[0][0].timestamp() < window_started_at:
        events.popleft()
    return events


def _provider_concurrency_slot(provider: Provider):
    if provider.max_concurrent_requests is None:
        return _NoopAsyncContext()
    stored = _provider_semaphores.get(provider.id)
    if stored is None or stored[0] != provider.max_concurrent_requests:
        semaphore = asyncio.Semaphore(provider.max_concurrent_requests)
        _provider_semaphores[provider.id] = (provider.max_concurrent_requests, semaphore)
        return semaphore
    _, semaphore = stored
    return semaphore


class _NoopAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _int_policy_value(
    value: object,
    fallback: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = fallback
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _status_policy_values(value: object, *, fallback: set[int]) -> set[int]:
    if not isinstance(value, list):
        return set(fallback)
    statuses = set()
    for item in value:
        try:
            status_code = int(item)
        except (TypeError, ValueError):
            continue
        if 100 <= status_code <= 599:
            statuses.add(status_code)
    return statuses or set(fallback)


async def _get_provider_or_raise(*, provider_id: UUID, scope: Scope, db: AsyncSession) -> Provider:
    provider = await repository.get_provider(provider_id=provider_id, org_id=scope.org_id, db=db)
    if provider is None:
        raise ProviderNotFoundError
    return provider
