from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis_client import RedisStorageError, get_redis_client

PROBE_LEASE_SECONDS = 30


class CircuitStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class CircuitPolicy:
    enabled: bool
    failure_threshold_pct: int
    min_request_count: int
    window_seconds: int
    cooldown_seconds: int

    @property
    def signature(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class CircuitPermission:
    state: str
    probe_token: str | None = None


@dataclass(frozen=True)
class CircuitSnapshot:
    state: str
    open_until: datetime | None
    failures: int
    successes: int


class CircuitBackend(Protocol):
    async def acquire(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        policy: CircuitPolicy,
    ) -> CircuitPermission: ...

    async def record_success(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        policy: CircuitPolicy,
        permission: CircuitPermission,
    ) -> str | None: ...

    async def record_failure(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        policy: CircuitPolicy,
        permission: CircuitPermission,
    ) -> str | None: ...

    async def abandon(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        policy: CircuitPolicy,
        permission: CircuitPermission,
    ) -> None: ...

    async def renew_probe(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        policy: CircuitPolicy,
        permission: CircuitPermission,
    ) -> bool: ...

    async def get_snapshots(
        self,
        providers: list[tuple[UUID, UUID, CircuitPolicy]],
    ) -> dict[UUID, CircuitSnapshot]: ...


@dataclass
class _MemoryState:
    events: deque[tuple[float, bool]]
    open_until: float | None = None
    probe_token: str | None = None
    probe_expires_at: float | None = None


class InMemoryCircuitBackend:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._states: dict[str, _MemoryState] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        *,
        org_id: UUID,
        provider_id: UUID,
        policy: CircuitPolicy,
    ) -> CircuitPermission:
        if not policy.enabled:
            return CircuitPermission("closed")
        async with self._lock:
            now = self._clock()
            state = self._state(org_id, provider_id, policy)
            self._prune(state, policy, now)
            if state.open_until is None:
                return CircuitPermission("closed")
            if state.open_until > now:
                return CircuitPermission("open")
            if state.probe_expires_at is not None and state.probe_expires_at > now:
                return CircuitPermission("open")
            token = secrets.token_urlsafe(24)
            state.probe_token = token
            state.probe_expires_at = now + PROBE_LEASE_SECONDS
            return CircuitPermission("half_open", token)

    async def record_success(self, **kwargs) -> str | None:
        async with self._lock:
            state, policy, permission = self._arguments(kwargs)
            now = self._clock()
            if permission.probe_token and not self._owns_probe(state, permission, now):
                return None
            if self._owns_probe(state, permission, now):
                state.events.clear()
                state.open_until = None
                state.probe_token = None
                state.probe_expires_at = None
                return "closed"
            state.events.append((now, True))
            self._prune(state, policy, now)
            return None

    async def record_failure(self, **kwargs) -> str | None:
        async with self._lock:
            state, policy, permission = self._arguments(kwargs)
            now = self._clock()
            if permission.probe_token and not self._owns_probe(state, permission, now):
                return None
            if self._owns_probe(state, permission, now):
                state.open_until = now + policy.cooldown_seconds
                state.probe_token = None
                state.probe_expires_at = None
                return "reopened"
            state.events.append((now, False))
            self._prune(state, policy, now)
            failures = sum(not succeeded for _, succeeded in state.events)
            if (
                len(state.events) >= policy.min_request_count
                and failures * 100 >= len(state.events) * policy.failure_threshold_pct
            ):
                transitioned = state.open_until is None
                state.open_until = now + policy.cooldown_seconds
                return "opened" if transitioned else None
            return None

    async def abandon(self, **kwargs) -> None:
        async with self._lock:
            state, _, permission = self._arguments(kwargs)
            if self._owns_probe(state, permission, self._clock()):
                state.probe_token = None
                state.probe_expires_at = None

    async def renew_probe(self, **kwargs) -> bool:
        async with self._lock:
            state, _, permission = self._arguments(kwargs)
            if self._owns_probe(state, permission, self._clock()):
                state.probe_expires_at = self._clock() + PROBE_LEASE_SECONDS
                return True
            return False

    async def get_snapshots(
        self,
        providers: list[tuple[UUID, UUID, CircuitPolicy]],
    ) -> dict[UUID, CircuitSnapshot]:
        snapshots: dict[UUID, CircuitSnapshot] = {}
        async with self._lock:
            now = self._clock()
            for org_id, provider_id, policy in providers:
                state = self._state(org_id, provider_id, policy)
                self._prune(state, policy, now)
                if state.open_until is None:
                    circuit_state = "closed"
                elif state.open_until > now:
                    circuit_state = "open"
                elif state.probe_expires_at is not None and state.probe_expires_at > now:
                    circuit_state = "half_open"
                else:
                    circuit_state = "open"
                snapshots[provider_id] = CircuitSnapshot(
                    state=circuit_state,
                    open_until=(
                        datetime.fromtimestamp(state.open_until, UTC)
                        if state.open_until is not None
                        else None
                    ),
                    failures=sum(not success for _, success in state.events),
                    successes=sum(success for _, success in state.events),
                )
        return snapshots

    def _state(
        self,
        org_id: UUID,
        provider_id: UUID,
        policy: CircuitPolicy,
    ) -> _MemoryState:
        key = f"{org_id}:{provider_id}:{policy.signature}"
        return self._states.setdefault(key, _MemoryState(deque()))

    def _arguments(self, kwargs) -> tuple[_MemoryState, CircuitPolicy, CircuitPermission]:
        policy = kwargs["policy"]
        return (
            self._state(kwargs["org_id"], kwargs["provider_id"], policy),
            policy,
            kwargs["permission"],
        )

    @staticmethod
    def _owns_probe(
        state: _MemoryState,
        permission: CircuitPermission,
        now: float,
    ) -> bool:
        return bool(
            permission.probe_token
            and permission.probe_token == state.probe_token
            and state.probe_expires_at is not None
            and state.probe_expires_at > now
        )

    @staticmethod
    def _prune(state: _MemoryState, policy: CircuitPolicy, now: float) -> None:
        cutoff = now - policy.window_seconds
        while state.events and state.events[0][0] < cutoff:
            state.events.popleft()


ACQUIRE_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local open_until = tonumber(redis.call('GET', KEYS[1]) or '0')
if open_until == 0 then return {'closed', ''} end
if open_until > now_ms then return {'open', ''} end
local acquired = redis.call('SET', KEYS[2], ARGV[1], 'NX', 'PX', ARGV[2])
if acquired then return {'half_open', ARGV[1]} end
return {'open', ''}
"""

OUTCOME_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local probe = redis.call('GET', KEYS[4])
if ARGV[1] ~= '' and probe ~= ARGV[1] then return '' end
if ARGV[1] ~= '' and probe == ARGV[1] then
  redis.call('DEL', KEYS[4])
  if ARGV[2] == 'success' then
    redis.call('DEL', KEYS[1], KEYS[2], KEYS[3])
  else
    redis.call('SET', KEYS[1], now_ms + tonumber(ARGV[6]), 'PX', ARGV[7])
  end
  return ARGV[2] == 'success' and 'closed' or 'reopened'
end
redis.call('ZADD', KEYS[2], now_ms, ARGV[3])
if ARGV[2] == 'failure' then redis.call('ZADD', KEYS[3], now_ms, ARGV[3]) end
local cutoff = now_ms - tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', cutoff)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', cutoff)
redis.call('PEXPIRE', KEYS[2], ARGV[7])
redis.call('PEXPIRE', KEYS[3], ARGV[7])
local total = redis.call('ZCARD', KEYS[2])
local failures = redis.call('ZCARD', KEYS[3])
if total >= tonumber(ARGV[5]) and failures * 100 >= total * tonumber(ARGV[8]) then
  local was_open = redis.call('EXISTS', KEYS[1])
  redis.call('SET', KEYS[1], now_ms + tonumber(ARGV[6]), 'PX', ARGV[7])
  if was_open == 0 then return 'opened' end
end
return ''
"""

SNAPSHOT_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local cutoff = now_ms - tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', cutoff)
redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', cutoff)
return {
  redis.call('GET', KEYS[1]) or '',
  redis.call('GET', KEYS[2]) or '',
  redis.call('ZCARD', KEYS[3]),
  redis.call('ZCARD', KEYS[4]),
  now_ms
}
"""


class RedisCircuitBackend:
    async def acquire(self, *, org_id, provider_id, policy) -> CircuitPermission:
        keys = self._keys(org_id, provider_id, policy)
        token = secrets.token_urlsafe(24)
        result = await self._eval(
            ACQUIRE_SCRIPT,
            [keys["open"], keys["probe"]],
            [token, PROBE_LEASE_SECONDS * 1000],
        )
        return CircuitPermission(str(result[0]), str(result[1]) or None)

    async def record_success(self, **kwargs) -> str | None:
        return await self._record("success", kwargs)

    async def record_failure(self, **kwargs) -> str | None:
        return await self._record("failure", kwargs)

    async def abandon(self, **kwargs) -> None:
        permission = kwargs["permission"]
        if not permission.probe_token:
            return
        keys = self._keys(kwargs["org_id"], kwargs["provider_id"], kwargs["policy"])
        script = (
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
            "return redis.call('DEL', KEYS[1]) end return 0"
        )
        await self._eval(script, [keys["probe"]], [permission.probe_token])

    async def renew_probe(self, **kwargs) -> bool:
        permission = kwargs["permission"]
        if not permission.probe_token:
            return False
        keys = self._keys(kwargs["org_id"], kwargs["provider_id"], kwargs["policy"])
        script = (
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
            "return redis.call('PEXPIRE', KEYS[1], ARGV[2]) end return 0"
        )
        result = await self._eval(
            script,
            [keys["probe"]],
            [permission.probe_token, PROBE_LEASE_SECONDS * 1000],
        )
        return bool(result)

    async def get_snapshots(self, providers) -> dict[UUID, CircuitSnapshot]:
        try:
            client = get_redis_client()
            pipeline = client.pipeline(transaction=False)
            keys_by_provider = {}
            for org_id, provider_id, policy in providers:
                keys = self._keys(org_id, provider_id, policy)
                keys_by_provider[provider_id] = keys
                pipeline.eval(
                    SNAPSHOT_SCRIPT,
                    4,
                    keys["open"],
                    keys["probe"],
                    keys["events"],
                    keys["failures"],
                    policy.window_seconds * 1000,
                )
            values = await pipeline.execute()
        except (RedisError, RedisStorageError, ValueError) as exc:
            raise CircuitStorageError("provider circuit storage error") from exc
        snapshots = {}
        for index, (_, provider_id, _) in enumerate(providers):
            open_until, probe, total, failures, now_ms = values[index]
            open_ms = int(open_until) if open_until else 0
            state = (
                "closed"
                if not open_ms
                else "open"
                if open_ms > now_ms
                else "half_open"
                if probe
                else "open"
            )
            snapshots[provider_id] = CircuitSnapshot(
                state=state,
                open_until=(
                    datetime.fromtimestamp(open_ms / 1000, UTC) if open_ms else None
                ),
                failures=int(failures),
                successes=max(0, int(total) - int(failures)),
            )
        return snapshots

    async def _record(self, outcome: str, kwargs) -> str | None:
        policy = kwargs["policy"]
        permission = kwargs["permission"]
        keys = self._keys(kwargs["org_id"], kwargs["provider_id"], policy)
        ttl_ms = (policy.window_seconds + policy.cooldown_seconds + PROBE_LEASE_SECONDS) * 2000
        result = await self._eval(
            OUTCOME_SCRIPT,
            [keys["open"], keys["events"], keys["failures"], keys["probe"]],
            [
                permission.probe_token or "",
                outcome,
                secrets.token_urlsafe(16),
                policy.window_seconds * 1000,
                policy.min_request_count,
                policy.cooldown_seconds * 1000,
                ttl_ms,
                policy.failure_threshold_pct,
            ],
        )
        return str(result) or None

    async def _eval(self, script: str, keys: list[str], args: list[object]):
        try:
            return await get_redis_client().eval(script, len(keys), *keys, *args)
        except (RedisError, RedisStorageError, ValueError) as exc:
            raise CircuitStorageError("provider circuit storage error") from exc

    @staticmethod
    def _keys(org_id: UUID, provider_id: UUID, policy: CircuitPolicy) -> dict[str, str]:
        prefix = f"bab:provider:circuit:{org_id}:{provider_id}:{policy.signature}"
        return {
            "open": f"{prefix}:open",
            "probe": f"{prefix}:probe",
            "events": f"{prefix}:events",
            "failures": f"{prefix}:failures",
        }


_backend: CircuitBackend | None = None


def get_circuit_backend() -> CircuitBackend:
    global _backend
    if _backend is None:
        _backend = (
            RedisCircuitBackend()
            if settings.provider_runtime_state_backend == "redis"
            else InMemoryCircuitBackend()
        )
    return _backend


def set_circuit_backend_for_tests(backend: CircuitBackend | None) -> None:
    global _backend
    _backend = backend
