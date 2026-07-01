from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

import structlog
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.metrics import (
    record_provider_concurrency_rejection,
    record_provider_concurrency_renewal_loss,
    record_provider_concurrency_storage_failure,
    record_provider_concurrency_wait,
)
from app.core.redis_client import RedisStorageError, get_redis_client
from app.modules.providers.errors import ProviderUpstreamError
from app.modules.providers.internal.models import Provider

logger = structlog.get_logger(__name__)


class ProviderConcurrencyStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConcurrencyPermit:
    token: str
    lease_seconds: int


class ProviderConcurrencyBackend(Protocol):
    async def acquire(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        limit: int,
        lease_seconds: int,
    ) -> ProviderConcurrencyPermit | None: ...

    async def release(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        permit: ProviderConcurrencyPermit,
    ) -> None: ...

    async def renew(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        permit: ProviderConcurrencyPermit,
    ) -> bool: ...


_provider_semaphores: dict[UUID, tuple[int, asyncio.Semaphore]] = {}
_redis_backend: ProviderConcurrencyBackend | None = None


def provider_concurrency_slot(
    provider: Provider,
    *,
    wait_timeout_seconds: int,
) -> AbstractAsyncContextManager[None]:
    if provider.max_concurrent_requests is None:
        return _NoopAsyncContext()
    if settings.provider_runtime_state_backend == "redis":
        return _RedisProviderConcurrencySlot(
            provider=provider,
            wait_timeout_seconds=wait_timeout_seconds,
        )
    return _memory_provider_concurrency_slot(provider)


def _memory_provider_concurrency_slot(provider: Provider) -> asyncio.Semaphore:
    stored = _provider_semaphores.get(provider.id)
    if stored is None or stored[0] != provider.max_concurrent_requests:
        semaphore = asyncio.Semaphore(provider.max_concurrent_requests)
        _provider_semaphores[provider.id] = (provider.max_concurrent_requests, semaphore)
        return semaphore
    _, semaphore = stored
    return semaphore


class RedisProviderConcurrencyBackend:
    async def acquire(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        limit: int,
        lease_seconds: int,
    ) -> ProviderConcurrencyPermit | None:
        token = secrets.token_urlsafe(24)
        result = await self._eval(
            ACQUIRE_SCRIPT,
            [self._key(org_id, provider_id)],
            [token, limit, lease_seconds * 1000],
        )
        return (
            ProviderConcurrencyPermit(token=token, lease_seconds=lease_seconds)
            if int(result[0])
            else None
        )

    async def release(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        permit: ProviderConcurrencyPermit,
    ) -> None:
        await self._eval(
            "return redis.call('ZREM', KEYS[1], ARGV[1])",
            [self._key(org_id, provider_id)],
            [permit.token],
        )

    async def renew(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        permit: ProviderConcurrencyPermit,
    ) -> bool:
        result = await self._eval(
            RENEW_SCRIPT,
            [self._key(org_id, provider_id)],
            [permit.token, permit.lease_seconds * 1000],
        )
        return bool(int(result))

    async def _eval(self, script: str, keys: list[str], args: list[object]):
        try:
            return await get_redis_client().eval(script, len(keys), *keys, *args)
        except (RedisError, RedisStorageError, ValueError) as exc:
            raise ProviderConcurrencyStorageError(
                "provider concurrency storage error"
            ) from exc

    @staticmethod
    def _key(org_id: UUID, provider_id: UUID) -> str:
        return f"bab:provider:concurrency:{org_id}:{provider_id}"


@dataclass
class _RedisProviderConcurrencySlot:
    provider: Provider
    wait_timeout_seconds: int
    permit: ProviderConcurrencyPermit | None = None
    renewal_task: asyncio.Task | None = None
    entered_at: float = field(default=0.0)

    async def __aenter__(self) -> None:
        backend = _get_redis_backend()
        deadline = time.monotonic() + self.wait_timeout_seconds
        lease_seconds = max(30, self.wait_timeout_seconds + 5)
        self.entered_at = time.monotonic()
        while True:
            try:
                self.permit = await backend.acquire(
                    org_id=self.provider.org_id,
                    provider_id=self.provider.id,
                    limit=self.provider.max_concurrent_requests,
                    lease_seconds=lease_seconds,
                )
            except ProviderConcurrencyStorageError as exc:
                record_provider_concurrency_storage_failure(backend="redis")
                record_provider_concurrency_wait(
                    backend="redis",
                    outcome="storage_unavailable",
                    duration_seconds=time.monotonic() - self.entered_at,
                )
                logger.warning(
                    "provider_concurrency_storage_failed",
                    provider_id=str(self.provider.id),
                    org_id=str(self.provider.org_id),
                    operation="acquire",
                )
                raise _provider_state_unavailable() from exc
            if self.permit is not None:
                record_provider_concurrency_wait(
                    backend="redis",
                    outcome="acquired",
                    duration_seconds=time.monotonic() - self.entered_at,
                )
                self.renewal_task = asyncio.create_task(self._renew_permit())
                return None
            if time.monotonic() >= deadline:
                record_provider_concurrency_rejection(backend="redis", reason="timeout")
                record_provider_concurrency_wait(
                    backend="redis",
                    outcome="timeout",
                    duration_seconds=time.monotonic() - self.entered_at,
                )
                raise ProviderUpstreamError(
                    status_code=503,
                    body={"error": "provider concurrency limit reached"},
                    failure_reason="provider_concurrency_timeout",
                )
            await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self._stop_renewal()
        if self.permit is None:
            return False
        try:
            await _get_redis_backend().release(
                org_id=self.provider.org_id,
                provider_id=self.provider.id,
                permit=self.permit,
            )
        except ProviderConcurrencyStorageError:
            record_provider_concurrency_storage_failure(backend="redis")
            logger.warning(
                "provider_concurrency_storage_failed",
                provider_id=str(self.provider.id),
                org_id=str(self.provider.org_id),
                operation="release",
            )
        self.permit = None
        return False

    async def _renew_permit(self) -> None:
        if self.permit is None:
            return
        interval = self.permit.lease_seconds / 3
        while True:
            await asyncio.sleep(interval)
            try:
                owned = await _get_redis_backend().renew(
                    org_id=self.provider.org_id,
                    provider_id=self.provider.id,
                    permit=self.permit,
                )
            except ProviderConcurrencyStorageError:
                record_provider_concurrency_storage_failure(backend="redis")
                logger.warning(
                    "provider_concurrency_storage_failed",
                    provider_id=str(self.provider.id),
                    org_id=str(self.provider.org_id),
                    operation="renew",
                )
                return
            if not owned:
                record_provider_concurrency_renewal_loss(backend="redis")
                logger.warning(
                    "provider_concurrency_permit_lost",
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


class _NoopAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _get_redis_backend() -> ProviderConcurrencyBackend:
    global _redis_backend
    if _redis_backend is None:
        _redis_backend = RedisProviderConcurrencyBackend()
    return _redis_backend


def set_provider_concurrency_backend_for_tests(
    backend: ProviderConcurrencyBackend | None,
) -> None:
    global _redis_backend
    _redis_backend = backend


def _provider_state_unavailable() -> ProviderUpstreamError:
    return ProviderUpstreamError(
        status_code=503,
        body={"error": "provider state unavailable"},
        failure_reason="provider_state_unavailable",
    )


ACQUIRE_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[2]) then
  redis.call('ZADD', KEYS[1], now_ms + tonumber(ARGV[3]), ARGV[1])
  redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]) * 3)
  return {1}
end
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]) * 3)
return {0}
"""

RENEW_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not score or tonumber(score) <= now_ms then return 0 end
redis.call('ZADD', KEYS[1], now_ms + tonumber(ARGV[2]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) * 3)
return 1
"""
