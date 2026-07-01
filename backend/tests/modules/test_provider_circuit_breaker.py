import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis.asyncio as redis

from app.core.redis_client import close_redis_client, set_redis_client_for_tests
from app.modules.providers.errors import ProviderUpstreamError
from app.modules.providers.internal import concurrency, execution
from app.modules.providers.internal.circuit_breaker import (
    CircuitPermission,
    CircuitPolicy,
    InMemoryCircuitBackend,
    RedisCircuitBackend,
    set_circuit_backend_for_tests,
)
from app.modules.providers.schemas import ProviderChatCompletionRequest


class Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class TrackingProbeBackend:
    def __init__(self) -> None:
        self.abandons = 0

    async def acquire(self, **kwargs) -> CircuitPermission:
        return CircuitPermission("half_open", "probe-token")

    async def abandon(self, **kwargs) -> None:
        self.abandons += 1

    async def renew_probe(self, **kwargs) -> bool:
        return True

    async def record_success(self, **kwargs):
        return None

    async def record_failure(self, **kwargs):
        return None


@pytest.fixture
def circuit():
    clock = Clock()
    backend = InMemoryCircuitBackend(clock=clock)
    policy = CircuitPolicy(
        enabled=True,
        failure_threshold_pct=50,
        min_request_count=2,
        window_seconds=60,
        cooldown_seconds=10,
    )
    return backend, clock, policy, uuid4(), uuid4()


@pytest.mark.asyncio
async def test_memory_circuit_opens_and_rejects_at_threshold(circuit) -> None:
    backend, _, policy, org_id, provider_id = circuit
    first = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)
    await backend.record_success(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=first,
    )
    second = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)

    transition = await backend.record_failure(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=second,
    )
    rejected = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)

    assert transition == "opened"
    assert rejected.state == "open"


@pytest.mark.asyncio
async def test_expired_events_are_pruned(circuit) -> None:
    backend, clock, policy, org_id, provider_id = circuit
    permission = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)
    await backend.record_failure(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=permission,
    )
    clock.advance(61)

    snapshot = (
        await backend.get_snapshots([(org_id, provider_id, policy)])
    )[provider_id]

    assert snapshot.failures == 0


@pytest.mark.asyncio
async def test_only_one_half_open_probe_and_success_closes(circuit) -> None:
    backend, clock, policy, org_id, provider_id = circuit
    for _ in range(2):
        permission = await backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
        )
        await backend.record_failure(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
            permission=permission,
        )
    clock.advance(11)

    probe = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)
    rejected = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)
    transition = await backend.record_success(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=probe,
    )
    closed = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)

    assert probe.state == "half_open"
    assert rejected.state == "open"
    assert transition == "closed"
    assert closed.state == "closed"


@pytest.mark.asyncio
async def test_half_open_failure_reopens_and_abandon_releases(circuit) -> None:
    backend, clock, policy, org_id, provider_id = circuit
    for _ in range(2):
        permission = await backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
        )
        await backend.record_failure(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
            permission=permission,
        )
    clock.advance(11)
    probe = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)
    await backend.abandon(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=probe,
    )
    replacement = await backend.acquire(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
    )

    transition = await backend.record_failure(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=replacement,
    )

    assert replacement.state == "half_open"
    assert transition == "reopened"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure"])
async def test_stale_probe_outcome_cannot_mutate_replacement(
    circuit,
    outcome: str,
) -> None:
    backend, clock, policy, org_id, provider_id = circuit
    for _ in range(2):
        permission = await backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
        )
        await backend.record_failure(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
            permission=permission,
        )
    clock.advance(11)
    stale = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)
    clock.advance(31)
    replacement = await backend.acquire(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
    )

    operation = getattr(backend, f"record_{outcome}")
    transition = await operation(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=stale,
    )
    snapshot = (
        await backend.get_snapshots([(org_id, provider_id, policy)])
    )[provider_id]

    assert replacement.state == "half_open"
    assert transition is None
    assert snapshot.state == "half_open"
    assert snapshot.failures == 2
    assert snapshot.successes == 0


@pytest.mark.asyncio
async def test_probe_renewal_reports_lost_ownership(circuit) -> None:
    backend, clock, policy, org_id, provider_id = circuit
    for _ in range(2):
        permission = await backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
        )
        await backend.record_failure(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
            permission=permission,
        )
    clock.advance(11)
    stale = await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)
    clock.advance(31)
    await backend.acquire(org_id=org_id, provider_id=provider_id, policy=policy)

    owned = await backend.renew_probe(
        org_id=org_id,
        provider_id=provider_id,
        policy=policy,
        permission=stale,
    )

    assert owned is False


@pytest.mark.asyncio
async def test_empty_provider_state_read_does_not_touch_backend() -> None:
    class UnexpectedBackend:
        async def get_snapshots(self, providers):
            raise AssertionError("backend should not be called")

    set_circuit_backend_for_tests(UnexpectedBackend())
    try:
        assert await execution.provider_operational_states([]) == {}
    finally:
        set_circuit_backend_for_tests(None)


@pytest.mark.asyncio
async def test_memory_concurrency_slot_limits_in_process(monkeypatch) -> None:
    monkeypatch.setattr(concurrency.settings, "provider_runtime_state_backend", "memory")
    provider = SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        max_concurrent_requests=1,
    )
    first_slot = concurrency.provider_concurrency_slot(
        provider,
        wait_timeout_seconds=1,
    )
    second_slot = concurrency.provider_concurrency_slot(
        provider,
        wait_timeout_seconds=1,
    )

    async with first_slot:
        entered = False

        async def wait_for_slot() -> None:
            nonlocal entered
            async with second_slot:
                entered = True

        task = asyncio.create_task(wait_for_slot())
        await asyncio.sleep(0)
        assert entered is False
    await asyncio.wait_for(task, timeout=1)
    assert entered is True


@pytest.mark.asyncio
async def test_redis_concurrency_timeout_raises_provider_error(monkeypatch) -> None:
    class FullBackend:
        async def acquire(self, **kwargs):
            return None

        async def release(self, **kwargs):
            raise AssertionError("release should not run")

        async def renew(self, **kwargs):
            raise AssertionError("renew should not run")

    monkeypatch.setattr(concurrency.settings, "provider_runtime_state_backend", "redis")
    concurrency.set_provider_concurrency_backend_for_tests(FullBackend())
    provider = SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        max_concurrent_requests=1,
    )
    slot = concurrency.provider_concurrency_slot(provider, wait_timeout_seconds=0)

    try:
        with pytest.raises(ProviderUpstreamError) as exc_info:
            async with slot:
                pass
    finally:
        concurrency.set_provider_concurrency_backend_for_tests(None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.failure_reason == "provider_concurrency_timeout"
    assert exc_info.value.body == {"error": "provider concurrency limit reached"}


@pytest.mark.asyncio
async def test_redis_concurrency_storage_error_fails_closed(monkeypatch) -> None:
    class FailingBackend:
        async def acquire(self, **kwargs):
            raise concurrency.ProviderConcurrencyStorageError("down")

        async def release(self, **kwargs):
            raise AssertionError("release should not run")

        async def renew(self, **kwargs):
            raise AssertionError("renew should not run")

    monkeypatch.setattr(concurrency.settings, "provider_runtime_state_backend", "redis")
    concurrency.set_provider_concurrency_backend_for_tests(FailingBackend())
    provider = SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        max_concurrent_requests=1,
    )

    try:
        with pytest.raises(ProviderUpstreamError) as exc_info:
            async with concurrency.provider_concurrency_slot(provider, wait_timeout_seconds=1):
                pass
    finally:
        concurrency.set_provider_concurrency_backend_for_tests(None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.failure_reason == "provider_state_unavailable"


@pytest.mark.asyncio
async def test_redis_concurrency_release_is_token_scoped(monkeypatch) -> None:
    released = []

    class TrackingBackend:
        async def acquire(self, **kwargs):
            return concurrency.ProviderConcurrencyPermit(
                token="owned-token",
                lease_seconds=30,
            )

        async def release(self, **kwargs):
            released.append(kwargs["permit"].token)

        async def renew(self, **kwargs):
            return True

    monkeypatch.setattr(concurrency.settings, "provider_runtime_state_backend", "redis")
    concurrency.set_provider_concurrency_backend_for_tests(TrackingBackend())
    provider = SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        max_concurrent_requests=1,
    )

    try:
        async with concurrency.provider_concurrency_slot(provider, wait_timeout_seconds=1):
            pass
    finally:
        concurrency.set_provider_concurrency_backend_for_tests(None)

    assert released == ["owned-token"]


@pytest.mark.asyncio
async def test_managed_stream_success_releases_concurrency_slot() -> None:
    released = False
    closed = False

    class Slot:
        async def __aexit__(self, exc_type, exc, tb):
            nonlocal released
            released = True

    class Circuit:
        finished = False

        async def success(self):
            self.finished = True

        async def abandon(self):
            return None

    async def chunks():
        yield b"data"

    async def close():
        nonlocal closed
        closed = True

    stream = execution._managed_provider_stream(
        stream=execution.ProviderChatCompletionStream(
            status_code=200,
            chunks=chunks(),
            close=close,
            media_type="text/event-stream",
        ),
        credential=None,
        db=None,
        concurrency_slot=Slot(),
        circuit=Circuit(),
    )

    assert [chunk async for chunk in stream.chunks] == [b"data"]
    assert released is True
    assert closed is True


@pytest.mark.asyncio
async def test_managed_stream_failure_releases_concurrency_slot() -> None:
    released = False
    closed = False

    class Slot:
        async def __aexit__(self, exc_type, exc, tb):
            nonlocal released
            released = True

    class Circuit:
        async def failure(self):
            return None

        async def abandon(self):
            return None

    async def chunks():
        raise RuntimeError("stream failed")
        yield b"unreachable"

    async def close():
        nonlocal closed
        closed = True

    stream = execution._managed_provider_stream(
        stream=execution.ProviderChatCompletionStream(
            status_code=200,
            chunks=chunks(),
            close=close,
            media_type="text/event-stream",
        ),
        credential=None,
        db=None,
        concurrency_slot=Slot(),
        circuit=Circuit(),
    )

    with pytest.raises(RuntimeError, match="stream failed"):
        [chunk async for chunk in stream.chunks]
    assert released is True
    assert closed is True


@pytest.mark.asyncio
async def test_managed_stream_close_releases_concurrency_slot() -> None:
    released = False
    closed = False

    class Slot:
        async def __aexit__(self, exc_type, exc, tb):
            nonlocal released
            released = True

    class Circuit:
        async def abandon(self):
            return None

    async def chunks():
        yield b"data"

    async def close():
        nonlocal closed
        closed = True

    stream = execution._managed_provider_stream(
        stream=execution.ProviderChatCompletionStream(
            status_code=200,
            chunks=chunks(),
            close=close,
            media_type="text/event-stream",
        ),
        credential=None,
        db=None,
        concurrency_slot=Slot(),
        circuit=Circuit(),
    )

    await stream.close()

    assert released is True
    assert closed is True


@pytest.mark.asyncio
async def test_managed_stream_close_releases_concurrency_slot_when_close_raises() -> None:
    released = 0
    abandoned = 0

    class Slot:
        async def __aexit__(self, exc_type, exc, tb):
            nonlocal released
            released += 1

    class Circuit:
        async def abandon(self):
            nonlocal abandoned
            abandoned += 1

    async def chunks():
        yield b"data"

    async def close():
        raise RuntimeError("close failed")

    stream = execution._managed_provider_stream(
        stream=execution.ProviderChatCompletionStream(
            status_code=200,
            chunks=chunks(),
            close=close,
            media_type="text/event-stream",
        ),
        credential=None,
        db=None,
        concurrency_slot=Slot(),
        circuit=Circuit(),
    )

    with pytest.raises(RuntimeError, match="close failed"):
        await stream.close()
    await stream.close()

    assert released == 1
    assert abandoned == 1


@pytest.mark.asyncio
async def test_managed_stream_success_releases_concurrency_slot_when_close_raises() -> None:
    released = 0
    successes = 0

    class Slot:
        async def __aexit__(self, exc_type, exc, tb):
            nonlocal released
            released += 1

    class Circuit:
        async def success(self):
            nonlocal successes
            successes += 1

        async def abandon(self):
            return None

    async def chunks():
        yield b"data"

    async def close():
        raise RuntimeError("close failed")

    stream = execution._managed_provider_stream(
        stream=execution.ProviderChatCompletionStream(
            status_code=200,
            chunks=chunks(),
            close=close,
            media_type="text/event-stream",
        ),
        credential=None,
        db=None,
        concurrency_slot=Slot(),
        circuit=Circuit(),
    )

    yielded = []
    with pytest.raises(RuntimeError, match="close failed"):
        async for chunk in stream.chunks:
            yielded.append(chunk)

    assert yielded == [b"data"]
    assert released == 1
    assert successes == 1


@pytest.mark.asyncio
async def test_lost_probe_ownership_stops_renewal_task(monkeypatch) -> None:
    class LostBackend:
        async def renew_probe(self, **kwargs) -> bool:
            return False

    provider = type(
        "Provider",
        (),
        {"id": uuid4(), "org_id": uuid4()},
    )()
    policy = CircuitPolicy(True, 50, 2, 60, 10)
    circuit = execution._CircuitExecution(
        provider=provider,
        policy=policy,
        permission=CircuitPermission("half_open", "old-token"),
    )
    set_circuit_backend_for_tests(LostBackend())
    monkeypatch.setattr(
        "app.modules.providers.internal.circuit_breaker.PROBE_LEASE_SECONDS",
        0,
    )
    try:
        circuit.renewal_task = asyncio.create_task(circuit._renew_probe())
        await circuit.renewal_task
    finally:
        set_circuit_backend_for_tests(None)

    assert circuit.renewal_task.done()


async def _patch_chat_execution(monkeypatch, provider, adapter) -> None:
    async def get_provider(**kwargs):
        return provider

    async def get_settings(**kwargs):
        return SimpleNamespace(
            default_request_timeout_seconds=30,
            default_retry_count=0,
        )

    async def route_credentials(**kwargs):
        return [None]

    async def api_key(**kwargs):
        return None

    monkeypatch.setattr(execution, "_get_provider_or_raise", get_provider)
    monkeypatch.setattr(
        execution.settings_facade,
        "get_organization_settings",
        get_settings,
    )
    monkeypatch.setattr(
        execution.credential_routing,
        "resolve_provider_credential_route",
        route_credentials,
    )
    monkeypatch.setattr(
        execution.credential_routing,
        "api_key_for_routed_credential",
        api_key,
    )
    monkeypatch.setattr(execution.default_adapter_registry, "get", lambda _kind: adapter)


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_semaphore_abandons_probe(
    monkeypatch,
) -> None:
    backend = TrackingProbeBackend()
    set_circuit_backend_for_tests(backend)
    provider = SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        is_active=True,
        base_url="https://provider.example/v1",
        adapter_type="test",
        request_timeout_seconds=30,
        retry_policy={},
        circuit_breaker_policy={
            "enabled": True,
            "failure_threshold_pct": 50,
            "min_request_count": 2,
            "window_seconds": 60,
            "cooldown_seconds": 30,
        },
        max_concurrent_requests=1,
    )
    adapter = SimpleNamespace()
    await _patch_chat_execution(monkeypatch, provider, adapter)
    blocker = asyncio.Semaphore(0)
    monkeypatch.setattr(
        execution,
        "provider_concurrency_slot",
        lambda _provider, *, wait_timeout_seconds: blocker,
    )

    task = asyncio.create_task(
        execution.create_chat_completion(
            provider_id=provider.id,
            payload=ProviderChatCompletionRequest(
                model="test",
                messages=[{"role": "user", "content": "test"}],
            ),
            scope=SimpleNamespace(org_id=provider.org_id),
            db=None,
            http_client=None,
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        set_circuit_backend_for_tests(None)

    assert backend.abandons == 1


@pytest.mark.asyncio
async def test_unexpected_local_error_after_acquisition_abandons_probe(
    monkeypatch,
) -> None:
    backend = TrackingProbeBackend()
    set_circuit_backend_for_tests(backend)
    provider = SimpleNamespace(
        id=uuid4(),
        org_id=uuid4(),
        is_active=True,
        base_url="https://provider.example/v1",
        adapter_type="test",
        request_timeout_seconds=30,
        retry_policy={},
        circuit_breaker_policy={
            "enabled": True,
            "failure_threshold_pct": 50,
            "min_request_count": 2,
            "window_seconds": 60,
            "cooldown_seconds": 30,
        },
        max_concurrent_requests=None,
    )

    class BrokenAdapter:
        async def create_chat_completion(self, **kwargs):
            raise RuntimeError("local failure")

    await _patch_chat_execution(monkeypatch, provider, BrokenAdapter())
    try:
        with pytest.raises(RuntimeError, match="local failure"):
            await execution.create_chat_completion(
                provider_id=provider.id,
                payload=ProviderChatCompletionRequest(
                    model="test",
                    messages=[{"role": "user", "content": "test"}],
                ),
                scope=SimpleNamespace(org_id=provider.org_id),
                db=None,
                http_client=None,
            )
    finally:
        set_circuit_backend_for_tests(None)

    assert backend.abandons == 1


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("BAB_TEST_REDIS_URL"),
    reason="BAB_TEST_REDIS_URL is not configured",
)
async def test_real_redis_provider_concurrency_permits_are_shared() -> None:
    client = redis.from_url(
        os.environ["BAB_TEST_REDIS_URL"],
        encoding="utf-8",
        decode_responses=True,
    )
    set_redis_client_for_tests(client)
    first_backend = concurrency.RedisProviderConcurrencyBackend()
    second_backend = concurrency.RedisProviderConcurrencyBackend()
    org_id = uuid4()
    provider_id = uuid4()

    try:
        first = await first_backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            limit=1,
            lease_seconds=1,
        )
        second = await second_backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            limit=1,
            lease_seconds=1,
        )

        assert first is not None
        assert second is None

        await second_backend.release(
            org_id=org_id,
            provider_id=provider_id,
            permit=concurrency.ProviderConcurrencyPermit(
                token="stale-token",
                lease_seconds=1,
            ),
        )
        still_blocked = await second_backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            limit=1,
            lease_seconds=1,
        )
        assert still_blocked is None

        await first_backend.release(
            org_id=org_id,
            provider_id=provider_id,
            permit=first,
        )
        after_release = await second_backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            limit=1,
            lease_seconds=1,
        )
        assert after_release is not None

        await asyncio.sleep(1.1)
        after_expiry = await first_backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            limit=1,
            lease_seconds=1,
        )
        assert after_expiry is not None

        concurrent_provider_id = uuid4()
        permits = await asyncio.gather(
            *[
                first_backend.acquire(
                    org_id=org_id,
                    provider_id=concurrent_provider_id,
                    limit=2,
                    lease_seconds=1,
                )
                for _ in range(8)
            ]
        )
        assert sum(permit is not None for permit in permits) == 2
    finally:
        prefix = f"bab:provider:concurrency:{org_id}:*"
        keys = [key async for key in client.scan_iter(match=prefix)]
        if keys:
            await client.delete(*keys)
        await close_redis_client()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("BAB_TEST_REDIS_URL"),
    reason="BAB_TEST_REDIS_URL is not configured",
)
async def test_real_redis_ignores_replaced_probe_outcomes(monkeypatch) -> None:
    client = redis.from_url(
        os.environ["BAB_TEST_REDIS_URL"],
        encoding="utf-8",
        decode_responses=True,
    )
    set_redis_client_for_tests(client)
    monkeypatch.setattr(
        "app.modules.providers.internal.circuit_breaker.PROBE_LEASE_SECONDS",
        1,
    )
    first_backend = RedisCircuitBackend()
    second_backend = RedisCircuitBackend()
    policy = CircuitPolicy(True, 50, 2, 60, 1)
    org_id = uuid4()
    provider_id = uuid4()

    try:
        for _ in range(2):
            permission = await first_backend.acquire(
                org_id=org_id,
                provider_id=provider_id,
                policy=policy,
            )
            await first_backend.record_failure(
                org_id=org_id,
                provider_id=provider_id,
                policy=policy,
                permission=permission,
            )
        await asyncio.sleep(1.1)
        stale = await first_backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
        )
        await asyncio.sleep(1.1)
        replacement = await second_backend.acquire(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
        )

        await first_backend.record_success(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
            permission=stale,
        )
        await first_backend.record_failure(
            org_id=org_id,
            provider_id=provider_id,
            policy=policy,
            permission=stale,
        )
        snapshot = (
            await second_backend.get_snapshots([(org_id, provider_id, policy)])
        )[provider_id]

        assert replacement.state == "half_open"
        assert snapshot.state == "half_open"

        concurrent_provider_id = uuid4()
        for _ in range(2):
            permission = await first_backend.acquire(
                org_id=org_id,
                provider_id=concurrent_provider_id,
                policy=policy,
            )
            await first_backend.record_failure(
                org_id=org_id,
                provider_id=concurrent_provider_id,
                policy=policy,
                permission=permission,
            )
        await asyncio.sleep(1.1)
        permissions = await asyncio.gather(
            first_backend.acquire(
                org_id=org_id,
                provider_id=concurrent_provider_id,
                policy=policy,
            ),
            second_backend.acquire(
                org_id=org_id,
                provider_id=concurrent_provider_id,
                policy=policy,
            ),
        )
        assert [permission.state for permission in permissions].count("half_open") == 1

        failure_provider_id = uuid4()
        failure_policy = CircuitPolicy(True, 100, 100, 60, 1)
        closed_permissions = await asyncio.gather(
            *[
                first_backend.acquire(
                    org_id=org_id,
                    provider_id=failure_provider_id,
                    policy=failure_policy,
                )
                for _ in range(10)
            ]
        )
        await asyncio.gather(
            *[
                first_backend.record_failure(
                    org_id=org_id,
                    provider_id=failure_provider_id,
                    policy=failure_policy,
                    permission=permission,
                )
                for permission in closed_permissions
            ]
        )
        failure_snapshot = (
            await second_backend.get_snapshots(
                [(org_id, failure_provider_id, failure_policy)]
            )
        )[failure_provider_id]
        assert failure_snapshot.failures == 10
    finally:
        prefix = f"bab:provider:circuit:{org_id}:*"
        keys = [key async for key in client.scan_iter(match=prefix)]
        if keys:
            await client.delete(*keys)
        await close_redis_client()


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_client_and_credential_responses_are_not_circuit_failures(status_code: int) -> None:
    error = ProviderUpstreamError(status_code=status_code, body=None)

    assert execution._is_circuit_failure(error) is False


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [
        (408, "timeout"),
        (429, "rate_limited"),
        (500, "provider_5xx"),
        (502, "connection_failed"),
        (502, "invalid_response"),
        (502, "stream_failed"),
    ],
)
def test_availability_failures_count_for_circuit(
    status_code: int,
    reason: str,
) -> None:
    error = ProviderUpstreamError(
        status_code=status_code,
        body=None,
        failure_reason=reason,
    )

    assert execution._is_circuit_failure(error) is True


@pytest.mark.parametrize(
    "reason",
    ["circuit_open", "credential_error", "provider_state_unavailable"],
)
def test_local_and_circuit_errors_do_not_count(reason: str) -> None:
    error = ProviderUpstreamError(status_code=503, body=None, failure_reason=reason)

    assert execution._is_circuit_failure(error) is False
