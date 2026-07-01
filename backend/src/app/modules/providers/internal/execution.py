import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import Scope, sqlite_write_coordinator
from app.core.metrics import (
    record_provider_circuit_rejection,
    record_provider_circuit_storage_failure,
    record_provider_circuit_transition,
)
from app.modules.providers.errors import (
    ProviderAdapterNotFoundError,
    ProviderCredentialRequiredError,
    ProviderInactiveError,
    ProviderNotFoundError,
    ProviderUpstreamError,
)
from app.modules.providers.internal import circuit_breaker, credential_routing, repository
from app.modules.providers.internal.adapters import (
    AdapterProvider,
    anthropic_messages_adapter,
    default_adapter_registry,
)
from app.modules.providers.internal.concurrency import provider_concurrency_slot
from app.modules.providers.internal.models import Provider, ProviderCredential
from app.modules.providers.internal.secret_backends import ProviderSecretBackendRegistry
from app.modules.providers.schemas import (
    ProviderAnthropicMessagesRequest,
    ProviderAnthropicMessagesResponse,
    ProviderChatCompletionRequest,
    ProviderChatCompletionResponse,
    ProviderChatCompletionStream,
)
from app.modules.settings import facade as settings_facade

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _StreamExecutionContext:
    provider: Provider
    request_timeout_seconds: int
    adapter: Any
    routed_credentials: list[ProviderCredential | None]


@dataclass
class _CircuitExecution:
    provider: Provider
    policy: circuit_breaker.CircuitPolicy
    permission: circuit_breaker.CircuitPermission
    renewal_task: asyncio.Task | None = None
    finished: bool = False
    finish_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    async def acquire(cls, provider: Provider) -> "_CircuitExecution":
        policy = circuit_policy(provider)
        if not policy.enabled:
            return cls(
                provider,
                policy,
                circuit_breaker.CircuitPermission("closed"),
            )
        try:
            permission = await circuit_breaker.get_circuit_backend().acquire(
                org_id=provider.org_id,
                provider_id=provider.id,
                policy=policy,
            )
        except circuit_breaker.CircuitStorageError as exc:
            record_provider_circuit_storage_failure(backend=_circuit_backend_label())
            raise _provider_state_unavailable() from exc
        if permission.state == "open":
            record_provider_circuit_rejection(backend=_circuit_backend_label())
            logger.warning(
                "provider_circuit_rejected",
                provider_id=str(provider.id),
                org_id=str(provider.org_id),
            )
            raise ProviderUpstreamError(
                status_code=503,
                body={"error": "provider circuit is open"},
                failure_reason="circuit_open",
            )
        if permission.state == "half_open":
            record_provider_circuit_transition(
                from_state="open",
                to_state="half_open",
                reason="cooldown_elapsed",
                backend=_circuit_backend_label(),
            )
            logger.warning(
                "provider_circuit_half_opened",
                provider_id=str(provider.id),
                org_id=str(provider.org_id),
            )
        execution = cls(provider, policy, permission)
        if permission.probe_token:
            execution.renewal_task = asyncio.create_task(execution._renew_probe())
        return execution

    async def success(self) -> None:
        await self._finish("success")

    async def failure(self) -> None:
        await self._finish("failure")

    async def abandon(self) -> None:
        await self._finish("abandon")

    async def _finish(self, outcome: str) -> None:
        async with self.finish_lock:
            if self.finished:
                return
            await self._stop_renewal()
            if not self.policy.enabled:
                self.finished = True
                return
            backend = circuit_breaker.get_circuit_backend()
            operation = {
                "success": backend.record_success,
                "failure": backend.record_failure,
                "abandon": backend.abandon,
            }[outcome]
            try:
                transition = await operation(
                    org_id=self.provider.org_id,
                    provider_id=self.provider.id,
                    policy=self.policy,
                    permission=self.permission,
                )
                if transition:
                    from_state, to_state, reason = {
                        "opened": ("closed", "open", "failure_threshold"),
                        "reopened": ("half_open", "open", "probe_failure"),
                        "closed": ("half_open", "closed", "probe_success"),
                    }[transition]
                    record_provider_circuit_transition(
                        from_state=from_state,
                        to_state=to_state,
                        reason=reason,
                        backend=_circuit_backend_label(),
                    )
                    event = {
                        "open": "provider_circuit_opened",
                        "closed": "provider_circuit_closed",
                    }[to_state]
                    logger.warning(
                        event,
                        provider_id=str(self.provider.id),
                        org_id=str(self.provider.org_id),
                        reason=reason,
                    )
            except circuit_breaker.CircuitStorageError:
                record_provider_circuit_storage_failure(backend=_circuit_backend_label())
                logger.warning(
                    "provider_circuit_storage_failed",
                    provider_id=str(self.provider.id),
                    org_id=str(self.provider.org_id),
                    operation=outcome,
                )
            self.finished = True

    async def _renew_probe(self) -> None:
        while True:
            await asyncio.sleep(circuit_breaker.PROBE_LEASE_SECONDS / 3)
            try:
                owned = await circuit_breaker.get_circuit_backend().renew_probe(
                    org_id=self.provider.org_id,
                    provider_id=self.provider.id,
                    policy=self.policy,
                    permission=self.permission,
                )
                if not owned:
                    logger.warning(
                        "provider_circuit_probe_lease_lost",
                        provider_id=str(self.provider.id),
                        org_id=str(self.provider.org_id),
                    )
                    return
            except circuit_breaker.CircuitStorageError:
                record_provider_circuit_storage_failure(
                    backend=_circuit_backend_label()
                )
                logger.warning(
                    "provider_circuit_probe_renewal_failed",
                    provider_id=str(self.provider.id),
                    org_id=str(self.provider.org_id),
                )
                return

    async def _stop_renewal(self) -> None:
        if self.renewal_task is None:
            return
        self.renewal_task.cancel()
        try:
            await self.renewal_task
        except asyncio.CancelledError:
            pass
        self.renewal_task = None


async def _mark_provider_credential_used(
    *, provider_credential: ProviderCredential, db: AsyncSession
) -> None:
    async with sqlite_write_coordinator(db):
        await repository.mark_provider_credential_used(
            provider_credential=provider_credential,
            db=db,
        )
        await db.commit()


async def _mark_provider_credential_failed(
    *,
    provider_credential: ProviderCredential,
    error: ProviderUpstreamError,
    db: AsyncSession,
) -> None:
    async with sqlite_write_coordinator(db):
        await credential_routing.mark_provider_credential_failed(
            provider_credential=provider_credential,
            error=error,
            db=db,
        )
        await db.commit()


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
    retry_policy = _retry_policy(provider)

    adapter = default_adapter_registry.get(provider.adapter_type)
    routed_credentials = await credential_routing.resolve_provider_credential_route(
        provider=provider,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    circuit = await _CircuitExecution.acquire(provider)
    try:
        last_error: ProviderUpstreamError | None = None
        async with provider_concurrency_slot(
            provider,
            wait_timeout_seconds=request_timeout_seconds,
        ):
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
                    await circuit.success()
                    if credential is not None:
                        await _mark_provider_credential_used(
                            provider_credential=credential, db=db
                        )
                        response.provider_credential_id = credential.id
                    return response
                except ProviderUpstreamError as exc:
                    last_error = exc
                    if credential is not None:
                        await _mark_provider_credential_failed(
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
            await _record_final_circuit_error(circuit, last_error)
            raise last_error
        raise ProviderCredentialRequiredError
    finally:
        await circuit.abandon()


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
    retry_policy = _retry_policy(provider)
    routed_credentials = await credential_routing.resolve_provider_credential_route(
        provider=provider,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    circuit = await _CircuitExecution.acquire(provider)
    try:
        last_error: ProviderUpstreamError | None = None
        async with provider_concurrency_slot(
            provider,
            wait_timeout_seconds=request_timeout_seconds,
        ):
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
                    await circuit.success()
                    if credential is not None:
                        await _mark_provider_credential_used(
                            provider_credential=credential, db=db
                        )
                        response.provider_credential_id = credential.id
                    return response
                except ProviderUpstreamError as exc:
                    last_error = exc
                    if credential is not None:
                        await _mark_provider_credential_failed(
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
            await _record_final_circuit_error(circuit, last_error)
            raise last_error
        raise ProviderCredentialRequiredError
    finally:
        await circuit.abandon()


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
    context = await _stream_execution_context(
        provider_id=provider_id,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    provider = context.provider
    circuit = await _CircuitExecution.acquire(provider)
    concurrency_slot = provider_concurrency_slot(
        provider,
        wait_timeout_seconds=context.request_timeout_seconds,
    )
    concurrency_entered = False
    stream_returned = False
    try:
        await concurrency_slot.__aenter__()
        concurrency_entered = True
        stream = await _stream_chat_completion_with_routed_credentials(
            context=context,
            provider_credential_id=provider_credential_id,
            payload=payload,
            db=db,
            http_client=http_client,
            secret_registry=secret_registry,
            concurrency_slot=concurrency_slot,
            circuit=circuit,
        )
        stream_returned = True
        return stream
    finally:
        if not stream_returned:
            await circuit.abandon()
            if concurrency_entered:
                await concurrency_slot.__aexit__(None, None, None)


async def _stream_execution_context(
    *,
    provider_id: UUID,
    pool_id: UUID | None,
    provider_credential_id: UUID | None,
    scope: Scope,
    db: AsyncSession,
) -> _StreamExecutionContext:
    provider = await _get_provider_or_raise(provider_id=provider_id, scope=scope, db=db)
    if not provider.is_active:
        raise ProviderInactiveError
    org_settings = await settings_facade.get_organization_settings(scope=scope, db=db)
    routed_credentials = await credential_routing.resolve_provider_credential_route(
        provider=provider,
        pool_id=pool_id,
        provider_credential_id=provider_credential_id,
        scope=scope,
        db=db,
    )
    return _StreamExecutionContext(
        provider=provider,
        request_timeout_seconds=(
            provider.request_timeout_seconds or org_settings.default_request_timeout_seconds
        ),
        adapter=default_adapter_registry.get(provider.adapter_type),
        routed_credentials=routed_credentials,
    )


async def _stream_chat_completion_with_routed_credentials(
    *,
    context: _StreamExecutionContext,
    provider_credential_id: UUID | None,
    payload: ProviderChatCompletionRequest,
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None,
    concurrency_slot,
    circuit: _CircuitExecution,
) -> ProviderChatCompletionStream:
    last_error: ProviderUpstreamError | None = None
    for credential in context.routed_credentials:
        try:
            stream = await _open_stream_for_credential(
                context=context,
                credential=credential,
                payload=payload,
                http_client=http_client,
                secret_registry=secret_registry,
                db=db,
            )
            return _managed_provider_stream(
                stream=stream,
                credential=credential,
                db=db,
                concurrency_slot=concurrency_slot,
                circuit=circuit,
            )
        except TimeoutError as exc:
            last_error = ProviderUpstreamError(
                status_code=504,
                body={"error": "provider request timed out"},
                failure_reason="timeout",
            )
            await _mark_stream_failure(
                credential=credential,
                error=last_error,
                db=db,
            )
            if provider_credential_id is not None:
                await _record_final_circuit_error(circuit, last_error)
                raise last_error from exc
        except httpx.RequestError as exc:
            last_error = ProviderUpstreamError(
                status_code=502,
                body={"error": "provider upstream connection failed"},
                failure_reason="connection_failed",
            )
            await _mark_stream_failure(
                credential=credential,
                error=last_error,
                db=db,
            )
            if provider_credential_id is not None:
                await _record_final_circuit_error(circuit, last_error)
                raise last_error from exc
        except ProviderUpstreamError as exc:
            last_error = exc
            await _mark_stream_failure(
                credential=credential,
                error=exc,
                db=db,
            )
            should_stop = (
                provider_credential_id is not None
                or not credential_routing.should_try_next_credential(exc)
            )
            if should_stop:
                await _record_final_circuit_error(circuit, last_error)
                raise
    if last_error is not None:
        await _record_final_circuit_error(circuit, last_error)
        raise last_error
    await circuit.abandon()
    raise ProviderCredentialRequiredError


async def _open_stream_for_credential(
    *,
    context: _StreamExecutionContext,
    credential: ProviderCredential | None,
    payload: ProviderChatCompletionRequest,
    http_client: httpx.AsyncClient,
    secret_registry: ProviderSecretBackendRegistry | None,
    db: AsyncSession,
) -> ProviderChatCompletionStream:
    async with asyncio.timeout(context.request_timeout_seconds):
        stream = await context.adapter.stream_chat_completion(
            provider=AdapterProvider(
                base_url=context.provider.base_url,
                api_key=await credential_routing.api_key_for_routed_credential(
                    provider=context.provider,
                    credential=credential,
                    secret_registry=secret_registry,
                ),
            ),
            payload=payload,
            http_client=http_client,
        )
    if credential is not None:
        await _mark_provider_credential_used(provider_credential=credential, db=db)
        stream.provider_credential_id = credential.id
    return stream


def _managed_provider_stream(
    *,
    stream: ProviderChatCompletionStream,
    credential: ProviderCredential | None,
    db: AsyncSession,
    concurrency_slot,
    circuit: _CircuitExecution,
) -> ProviderChatCompletionStream:
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
        await circuit.abandon()
        try:
            await close_stream()
        finally:
            await concurrency_slot.__aexit__(None, None, None)

    async def managed_chunks(
        chunks: AsyncIterator[bytes] = original_chunks,
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
            await _mark_stream_failure(
                credential=credential,
                error=error,
                db=db,
            )
            await _record_final_circuit_error(circuit, error)
            raise
        else:
            await circuit.success()
        finally:
            await release_stream()

    stream.chunks = managed_chunks()
    stream.close = release_stream
    return stream


async def _mark_stream_failure(
    *,
    credential: ProviderCredential | None,
    error: ProviderUpstreamError,
    db: AsyncSession,
) -> None:
    if credential is not None:
        await _mark_provider_credential_failed(
            provider_credential=credential,
            error=error,
            db=db,
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
            # A transport failure after starting a non-idempotent provider POST is
            # ambiguous: the provider might still have received or processed it.
            raise ProviderUpstreamError(
                status_code=502,
                body={"error": "provider upstream connection failed"},
                failure_reason="connection_failed",
            ) from exc
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


def _retry_policy(provider: Provider) -> dict:
    stored = provider.retry_policy if isinstance(provider.retry_policy, dict) else {}
    return {
        "enabled": bool(stored.get("enabled", False)),
        "max_attempts": _int_policy_value(
            stored.get("max_attempts"),
            1,
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


def circuit_policy(provider: Provider) -> circuit_breaker.CircuitPolicy:
    stored = (
        provider.circuit_breaker_policy if isinstance(provider.circuit_breaker_policy, dict) else {}
    )
    return circuit_breaker.CircuitPolicy(
        enabled=bool(stored.get("enabled", False)),
        failure_threshold_pct=_int_policy_value(
            stored.get("failure_threshold_pct"),
            50,
            minimum=0,
            maximum=100,
        ),
        min_request_count=_int_policy_value(
            stored.get("min_request_count"),
            20,
            minimum=0,
        ),
        window_seconds=_int_policy_value(
            stored.get("window_seconds"),
            60,
            minimum=1,
        ),
        cooldown_seconds=_int_policy_value(
            stored.get("cooldown_seconds"),
            30,
            minimum=1,
        ),
    )


async def provider_operational_states(
    providers: list[Provider],
) -> dict[UUID, circuit_breaker.CircuitSnapshot]:
    if not providers:
        return {}
    try:
        return await circuit_breaker.get_circuit_backend().get_snapshots(
            [
                (provider.org_id, provider.id, circuit_policy(provider))
                for provider in providers
            ]
        )
    except circuit_breaker.CircuitStorageError as exc:
        record_provider_circuit_storage_failure(backend=_circuit_backend_label())
        logger.warning("provider_circuit_storage_failed", operation="snapshot")
        raise _provider_state_unavailable() from exc


async def _record_final_circuit_error(
    circuit: _CircuitExecution,
    error: ProviderUpstreamError,
) -> None:
    if _is_circuit_failure(error):
        await circuit.failure()
    elif error.failure_reason in {
        "circuit_open",
        "credential_error",
        "provider_state_unavailable",
    }:
        await circuit.abandon()
    else:
        await circuit.success()


def _is_circuit_failure(error: ProviderUpstreamError) -> bool:
    if error.failure_reason in {
        "circuit_open",
        "credential_error",
        "provider_state_unavailable",
    }:
        return False
    return (
        error.failure_reason
        in {"timeout", "rate_limited", "connection_failed", "stream_failed", "invalid_response"}
        or error.status_code in {408, 429}
        or error.status_code >= 500
    )


def _provider_state_unavailable() -> ProviderUpstreamError:
    return ProviderUpstreamError(
        status_code=503,
        body={"error": "provider state unavailable"},
        failure_reason="provider_state_unavailable",
    )


def _circuit_backend_label() -> str:
    return settings.provider_runtime_state_backend


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
