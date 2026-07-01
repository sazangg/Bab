from __future__ import annotations

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings


class RedisStorageError(RuntimeError):
    pass


_client: Redis | None = None


def get_redis_client() -> Redis:
    global _client
    if _client is not None:
        return _client
    if not settings.redis_url:
        raise RedisStorageError("Redis is not configured")
    try:
        _client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    except (RedisError, ValueError) as exc:
        raise RedisStorageError("Redis storage error") from exc
    return _client


async def ping_redis() -> None:
    try:
        await get_redis_client().ping()
    except (RedisError, ValueError) as exc:
        raise RedisStorageError("Redis storage error") from exc


async def close_redis_client() -> None:
    global _client
    client = _client
    _client = None
    if client is not None:
        try:
            await client.aclose()
        except RedisError as exc:
            raise RedisStorageError("Redis storage error") from exc


def set_redis_client_for_tests(client: Redis | None) -> None:
    global _client
    _client = client
