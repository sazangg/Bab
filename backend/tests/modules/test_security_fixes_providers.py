"""Regression tests for the provider SSRF guard and retry-idempotency fixes."""

import pytest

from app.core.ssrf import SsrfValidationError, assert_public_url
from app.modules.providers.errors import ProviderUpstreamError
from app.modules.providers.internal.execution import _call_with_retries

# --- #1 SSRF: provider base_url must resolve to a public address -------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8000/v1",  # loopback
        "http://10.0.0.5/v1",  # RFC1918
        "http://192.168.1.10/v1",  # RFC1918
        "http://[::1]/v1",  # IPv6 loopback
        "http://localhost/v1",  # resolves to loopback
        "ftp://example.com/v1",  # wrong scheme
    ],
)
def test_assert_public_url_rejects_non_public_targets(url: str) -> None:
    with pytest.raises(SsrfValidationError):
        assert_public_url(url)


def test_assert_public_url_allows_public_ip_literal() -> None:
    # A public IP literal needs no DNS and must be accepted.
    assert_public_url("https://1.1.1.1/v1")


# --- #15 a client-side timeout is not retried (non-idempotent POST) ----------


@pytest.mark.asyncio
async def test_call_with_retries_does_not_replay_on_timeout() -> None:
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError

    retry_policy = {
        "enabled": True,
        "max_attempts": 3,
        "backoff": "constant",
        "initial_delay_ms": 0,
        "max_delay_ms": 0,
        "retry_on_status": [504],  # even though 504 is "retryable", a timeout must not replay
    }
    with pytest.raises(ProviderUpstreamError) as excinfo:
        await _call_with_retries(
            call=call,
            request_timeout_seconds=30,
            retry_policy=retry_policy,
        )
    assert excinfo.value.status_code == 504
    assert excinfo.value.failure_reason == "timeout"
    assert calls == 1
