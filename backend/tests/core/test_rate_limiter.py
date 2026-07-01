import pytest

from app.core import rate_limiter
from app.core.rate_limiter import (
    InMemoryRateLimitBackend,
    RateLimitRule,
    RateLimitStorageError,
    close_rate_limit_backend,
    inspect_rate_limits,
    rate_limit_key,
    record_rate_limit_attempt,
    set_rate_limit_backend,
)


class FailingBackend:
    async def inspect(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        raise RateLimitStorageError("boom")

    async def increment(self, *, key: str, window_seconds: int) -> tuple[int, int]:
        raise RateLimitStorageError("boom")

    async def ping(self) -> None:
        raise RateLimitStorageError("boom")

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_rate_limiter(monkeypatch):
    set_rate_limit_backend(None)
    monkeypatch.setattr(rate_limiter.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limiter.settings, "rate_limit_fail_closed", True)
    yield
    set_rate_limit_backend(None)


@pytest.mark.asyncio
async def test_rate_limiter_allows_threshold_then_rejects() -> None:
    set_rate_limit_backend(InMemoryRateLimitBackend())
    rule = RateLimitRule("auth_login", "email", "person@example.com", 2, 60)

    first = await record_rate_limit_attempt([rule])
    second = await record_rate_limit_attempt([rule])
    third = await record_rate_limit_attempt([rule])

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after_seconds > 0
    assert third.bucket_type == "email"


@pytest.mark.asyncio
async def test_inspection_does_not_increment_bucket() -> None:
    backend = InMemoryRateLimitBackend()
    set_rate_limit_backend(backend)
    rule = RateLimitRule("proxy_auth", "key", "bab-sk-invalid", 1, 60)

    assert (await inspect_rate_limits([rule])).allowed is True
    assert (await inspect_rate_limits([rule])).allowed is True
    assert (await record_rate_limit_attempt([rule])).allowed is True
    assert (await inspect_rate_limits([rule])).allowed is True
    assert (await record_rate_limit_attempt([rule])).allowed is False


def test_rate_limit_keys_hash_sensitive_identifiers() -> None:
    rule = RateLimitRule("auth_login", "email", "person@example.com", 2, 60)

    key = rate_limit_key(rule)

    assert key.startswith("bab:rate:auth_login:email:")
    assert "person@example.com" not in key


@pytest.mark.asyncio
async def test_storage_error_fails_closed_when_configured() -> None:
    set_rate_limit_backend(FailingBackend())
    rule = RateLimitRule("auth_login", "ip", "203.0.113.10", 20, 60)

    decision = await record_rate_limit_attempt([rule])

    assert decision.allowed is False
    assert decision.retry_after_seconds == 60


@pytest.mark.asyncio
async def test_inspection_storage_error_fails_closed_when_configured() -> None:
    set_rate_limit_backend(FailingBackend())
    rule = RateLimitRule("proxy_auth", "ip", "203.0.113.10", 20, 60)

    decision = await inspect_rate_limits([rule])

    assert decision.allowed is False


@pytest.mark.asyncio
async def test_storage_error_can_fail_open(monkeypatch) -> None:
    set_rate_limit_backend(FailingBackend())
    monkeypatch.setattr(rate_limiter.settings, "rate_limit_fail_closed", False)
    rule = RateLimitRule("auth_login", "ip", "203.0.113.10", 20, 60)

    decision = await record_rate_limit_attempt([rule])

    assert decision.allowed is True


@pytest.mark.asyncio
async def test_inspection_storage_error_can_fail_open(monkeypatch) -> None:
    set_rate_limit_backend(FailingBackend())
    monkeypatch.setattr(rate_limiter.settings, "rate_limit_fail_closed", False)
    rule = RateLimitRule("proxy_auth", "ip", "203.0.113.10", 20, 60)

    assert (await inspect_rate_limits([rule])).allowed is True


@pytest.mark.asyncio
async def test_backend_construction_error_obeys_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(rate_limiter.settings, "redis_url", "redis://localhost")

    def fail_from_url(*args, **kwargs):
        raise ValueError("invalid URL")

    monkeypatch.setattr(rate_limiter, "get_redis_client", fail_from_url)
    rule = RateLimitRule("auth_login", "ip", "203.0.113.10", 20, 60)

    assert (await record_rate_limit_attempt([rule])).allowed is False


@pytest.mark.asyncio
async def test_backend_close_is_idempotent() -> None:
    set_rate_limit_backend(InMemoryRateLimitBackend())

    await close_rate_limit_backend()
    await close_rate_limit_backend()
