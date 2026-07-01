import pytest

from app.core import redis_client


class FakeRedis:
    def __init__(self) -> None:
        self.pings = 0
        self.closes = 0

    async def ping(self) -> None:
        self.pings += 1

    async def aclose(self) -> None:
        self.closes += 1


@pytest.fixture(autouse=True)
def reset_client():
    redis_client.set_redis_client_for_tests(None)
    yield
    redis_client.set_redis_client_for_tests(None)


@pytest.mark.asyncio
async def test_injected_redis_client_pings_and_closes_once() -> None:
    client = FakeRedis()
    redis_client.set_redis_client_for_tests(client)

    assert redis_client.get_redis_client() is client
    await redis_client.ping_redis()
    await redis_client.close_redis_client()
    await redis_client.close_redis_client()

    assert client.pings == 1
    assert client.closes == 1


def test_redis_client_construction_error_is_normalized(monkeypatch) -> None:
    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://localhost")

    def fail(*args, **kwargs):
        raise ValueError("secret URL detail")

    monkeypatch.setattr(redis_client.redis, "from_url", fail)

    with pytest.raises(redis_client.RedisStorageError, match="Redis storage error"):
        redis_client.get_redis_client()
