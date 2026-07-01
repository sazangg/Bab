from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Protocol

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis_client import RedisStorageError, get_redis_client

REDIS_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
if ttl < 0 then
  ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""

REDIS_INSPECT_SCRIPT = """
local current = tonumber(redis.call("GET", KEYS[1]) or "0")
local ttl = redis.call("TTL", KEYS[1])
if ttl < 0 then
  ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""


class RateLimitStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitRule:
    route_group: str
    bucket_type: str
    identifier: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    route_group: str
    bucket_type: str
    limit: int
    current: int
    window_seconds: int
    retry_after_seconds: int


class RateLimitBackend(Protocol):
    async def inspect(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        pass

    async def increment(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        pass

    async def ping(self) -> None:
        pass

    async def close(self) -> None:
        pass


class RedisRateLimitBackend:
    def __init__(self) -> None:
        try:
            self._client = get_redis_client()
        except (RedisStorageError, ValueError) as exc:
            raise RateLimitStorageError("rate limiter storage error") from exc

    async def inspect(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        try:
            current, ttl = await self._client.eval(
                REDIS_INSPECT_SCRIPT,
                1,
                key,
                window_seconds,
            )
        except (RedisError, ValueError) as exc:
            raise RateLimitStorageError("rate limiter storage error") from exc
        return int(current), max(1, int(ttl))

    async def increment(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        try:
            current, ttl = await self._client.eval(REDIS_SCRIPT, 1, key, window_seconds)
        except (RedisError, ValueError) as exc:
            raise RateLimitStorageError("rate limiter storage error") from exc
        return int(current), max(1, int(ttl))

    async def ping(self) -> None:
        try:
            await self._client.ping()
        except (RedisError, ValueError) as exc:
            raise RateLimitStorageError("rate limiter storage error") from exc

    async def close(self) -> None:
        return None


class InMemoryRateLimitBackend:
    def __init__(self) -> None:
        self._values: dict[str, tuple[int, float]] = {}

    async def inspect(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.monotonic()
        current, expires_at = self._values.get(key, (0, now + window_seconds))
        if expires_at <= now:
            self._values.pop(key, None)
            return 0, window_seconds
        return current, max(1, int(expires_at - now))

    async def increment(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.monotonic()
        current, expires_at = self._values.get(key, (0, now + window_seconds))
        if expires_at <= now:
            current = 0
            expires_at = now + window_seconds
        current += 1
        self._values[key] = (current, expires_at)
        return current, max(1, int(expires_at - now))

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def clear(self) -> None:
        self._values.clear()


_backend: RateLimitBackend | None = None


def set_rate_limit_backend(backend: RateLimitBackend | None) -> None:
    global _backend
    _backend = backend


def bucket_hash(value: str) -> str:
    return hmac.new(
        settings.secret_key.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


def rate_limit_key(rule: RateLimitRule) -> str:
    return f"bab:rate:{rule.route_group}:{rule.bucket_type}:{bucket_hash(rule.identifier)}"


async def inspect_rate_limits(rules: list[RateLimitRule]) -> RateLimitDecision:
    return await _evaluate_rate_limits(rules, operation="inspect")


async def record_rate_limit_attempt(rules: list[RateLimitRule]) -> RateLimitDecision:
    return await _evaluate_rate_limits(rules, operation="increment")


async def _evaluate_rate_limits(
    rules: list[RateLimitRule],
    *,
    operation: str,
) -> RateLimitDecision:
    if not settings.rate_limit_enabled:
        return _allowed_decision(rules)
    for rule in rules:
        try:
            backend = _get_backend()
            backend_operation = (
                backend.inspect if operation == "inspect" else backend.increment
            )
            current, retry_after = await backend_operation(
                key=rate_limit_key(rule),
                window_seconds=rule.window_seconds,
            )
        except RateLimitStorageError:
            if settings.rate_limit_fail_closed:
                return RateLimitDecision(
                    allowed=False,
                    route_group=rule.route_group,
                    bucket_type=rule.bucket_type,
                    limit=rule.limit,
                    current=rule.limit + 1,
                    window_seconds=rule.window_seconds,
                    retry_after_seconds=rule.window_seconds,
                )
            continue
        if current > rule.limit:
            return RateLimitDecision(
                allowed=False,
                route_group=rule.route_group,
                bucket_type=rule.bucket_type,
                limit=rule.limit,
                current=current,
                window_seconds=rule.window_seconds,
                retry_after_seconds=retry_after,
            )
    return _allowed_decision(rules)


async def close_rate_limit_backend() -> None:
    global _backend
    backend = _backend
    _backend = None
    if backend is not None:
        await backend.close()


def _allowed_decision(rules: list[RateLimitRule]) -> RateLimitDecision:
    rule = rules[0] if rules else RateLimitRule("unknown", "unknown", "none", 0, 1)
    return RateLimitDecision(
        allowed=True,
        route_group=rule.route_group,
        bucket_type=rule.bucket_type,
        limit=rule.limit,
        current=0,
        window_seconds=rule.window_seconds,
        retry_after_seconds=0,
    )


def _get_backend() -> RateLimitBackend:
    global _backend
    if _backend is None:
        if not settings.redis_url:
            raise RateLimitStorageError("rate limiter storage is not configured")
        _backend = RedisRateLimitBackend()
    return _backend
