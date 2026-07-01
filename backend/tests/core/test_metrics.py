import pytest
from httpx import ASGITransport, AsyncClient

from app.core.metrics import (
    metrics_response,
    record_gateway_denial,
    record_gateway_provider_attempt,
    record_gateway_request_finalized,
    record_gateway_route_attempt_finalized,
    record_http_request,
    record_provider_circuit_rejection,
    record_provider_circuit_storage_failure,
    record_provider_circuit_transition,
    record_provider_concurrency_rejection,
    record_provider_concurrency_renewal_loss,
    record_provider_concurrency_storage_failure,
    record_provider_concurrency_wait,
    record_rate_limit_rejection,
)


def test_metrics_response_uses_prometheus_content_type() -> None:
    response = metrics_response()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")


def test_metrics_helpers_emit_expected_metric_families() -> None:
    record_http_request(
        method="GET",
        route="/test/metrics",
        status_code=204,
        duration_seconds=0.01,
    )
    record_gateway_request_finalized(
        gateway_endpoint="test_endpoint",
        status_code=502,
        error_code=None,
    )
    record_gateway_route_attempt_finalized(
        status_code=502,
        status="failed",
        error_code="test_error",
        duration_seconds=0.02,
    )
    record_gateway_provider_attempt(
        gateway_endpoint="test_endpoint",
        status_code=200,
        error_code=None,
        duration_seconds=0.03,
    )
    record_gateway_denial(
        denial_type="test_denial",
        gateway_endpoint="test_endpoint",
        phase="request",
    )

    body = metrics_response().body.decode()

    assert _sample_with_labels(
        body,
        "bab_http_requests_total",
        ['method="GET"', 'route="/test/metrics"', 'status_class="2xx"', 'outcome="succeeded"'],
    )
    assert _sample_with_labels(
        body,
        "bab_gateway_requests_total",
        [
            'gateway_endpoint="test_endpoint"',
            'status_class="5xx"',
            'outcome="failed"',
            'error_code="none"',
        ],
    )
    assert _sample_with_labels(
        body,
        "bab_gateway_route_attempts_total",
        [
            'status="failed"',
            'status_class="5xx"',
            'outcome="failed"',
            'error_code="test_error"',
        ],
    )
    assert _sample_with_labels(
        body,
        "bab_gateway_provider_attempts_total",
        [
            'gateway_endpoint="test_endpoint"',
            'status_class="2xx"',
            'outcome="succeeded"',
            'error_code="none"',
        ],
    )
    assert _sample_with_labels(
        body,
        "bab_gateway_denials_total",
        [
            'denial_type="test_denial"',
            'gateway_endpoint="test_endpoint"',
            'phase="request"',
        ],
    )


def test_rate_limit_rejection_metric_is_exposed() -> None:
    record_rate_limit_rejection(route_group="auth_login", bucket_type="email")

    body = metrics_response().body.decode()

    assert _sample_with_labels(
        body,
        "bab_rate_limit_rejections_total",
        ['route_group="auth_login"', 'bucket_type="email"'],
    )


def test_provider_circuit_metrics_are_exposed() -> None:
    record_provider_circuit_transition(
        from_state="closed",
        to_state="open",
        reason="failure_threshold",
        backend="memory",
    )
    record_provider_circuit_rejection(backend="memory")
    record_provider_circuit_storage_failure(backend="redis")

    body = metrics_response().body.decode()

    assert "bab_provider_circuit_transitions_total" in body
    assert "bab_provider_circuit_rejections_total" in body
    assert "bab_provider_circuit_storage_failures_total" in body


def test_provider_concurrency_metrics_are_exposed() -> None:
    record_provider_concurrency_rejection(backend="redis", reason="timeout")
    record_provider_concurrency_storage_failure(backend="redis")
    record_provider_concurrency_renewal_loss(backend="redis")
    record_provider_concurrency_wait(
        backend="redis",
        outcome="acquired",
        duration_seconds=0.01,
    )

    body = metrics_response().body.decode()

    assert _sample_with_labels(
        body,
        "bab_provider_concurrency_rejections_total",
        ['backend="redis"', 'reason="timeout"'],
    )
    assert _sample_with_labels(
        body,
        "bab_provider_concurrency_storage_failures_total",
        ['backend="redis"'],
    )
    assert _sample_with_labels(
        body,
        "bab_provider_concurrency_renewal_losses_total",
        ['backend="redis"'],
    )
    assert _sample_with_labels(
        body,
        "bab_provider_concurrency_wait_seconds_bucket",
        ['backend="redis"', 'outcome="acquired"'],
    )


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_text(app_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")
    assert "# HELP bab_http_requests_total" in response.text


@pytest.mark.asyncio
async def test_http_middleware_records_request_metric(app_client) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_client),
        base_url="http://testserver",
    ) as client:
        health_response = await client.get("/api/v1/health")
        metrics = await client.get("/metrics")

    assert health_response.status_code == 200
    assert _sample_with_labels(
        metrics.text,
        "bab_http_requests_total",
        [
            'method="GET"',
            'route="/api/v1/health"',
            'status_class="2xx"',
            'outcome="succeeded"',
        ],
    )
    assert 'route="/metrics"' not in metrics.text


def _sample_with_labels(body: str, metric_name: str, labels: list[str]) -> bool:
    for line in body.splitlines():
        if not line.startswith(metric_name):
            continue
        if all(label in line for label in labels):
            return True
    return False
