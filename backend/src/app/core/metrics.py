from collections.abc import Callable

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.core.observability import outcome_for_status, status_class

UNKNOWN = "unknown"
NONE = "none"

HTTP_REQUESTS_TOTAL = Counter(
    "bab_http_requests_total",
    "HTTP requests handled by Bab.",
    ("method", "route", "status_class", "outcome"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "bab_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route", "status_class", "outcome"),
)
GATEWAY_REQUESTS_TOTAL = Counter(
    "bab_gateway_requests_total",
    "Gateway requests finalized by Bab.",
    ("gateway_endpoint", "status_class", "outcome", "error_code"),
)
GATEWAY_ROUTE_ATTEMPTS_TOTAL = Counter(
    "bab_gateway_route_attempts_total",
    "Gateway route attempts finalized by Bab.",
    ("status", "status_class", "outcome", "error_code"),
)
GATEWAY_ROUTE_ATTEMPT_DURATION_SECONDS = Histogram(
    "bab_gateway_route_attempt_duration_seconds",
    "Gateway route attempt duration in seconds.",
    ("status", "status_class", "outcome", "error_code"),
)
GATEWAY_PROVIDER_ATTEMPTS_TOTAL = Counter(
    "bab_gateway_provider_attempts_total",
    "Gateway provider attempts completed by Bab.",
    ("gateway_endpoint", "status_class", "outcome", "error_code"),
)
GATEWAY_PROVIDER_ATTEMPT_DURATION_SECONDS = Histogram(
    "bab_gateway_provider_attempt_duration_seconds",
    "Gateway provider attempt duration in seconds.",
    ("gateway_endpoint", "status_class", "outcome", "error_code"),
)
GATEWAY_DENIALS_TOTAL = Counter(
    "bab_gateway_denials_total",
    "Gateway denials and blocks recorded by Bab.",
    ("denial_type", "gateway_endpoint", "phase"),
)
RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "bab_rate_limit_rejections_total",
    "Rate-limit rejections emitted by Bab.",
    ("route_group", "bucket_type"),
)
PROVIDER_CIRCUIT_TRANSITIONS_TOTAL = Counter(
    "bab_provider_circuit_transitions_total",
    "Provider circuit state transitions.",
    ("from_state", "to_state", "reason", "backend"),
)
PROVIDER_CIRCUIT_REJECTIONS_TOTAL = Counter(
    "bab_provider_circuit_rejections_total",
    "Provider operations rejected by an open circuit.",
    ("backend",),
)
PROVIDER_CIRCUIT_STORAGE_FAILURES_TOTAL = Counter(
    "bab_provider_circuit_storage_failures_total",
    "Provider circuit storage failures.",
    ("backend",),
)
PROVIDER_CONCURRENCY_REJECTIONS_TOTAL = Counter(
    "bab_provider_concurrency_rejections_total",
    "Provider concurrency rejections.",
    ("backend", "reason"),
)
PROVIDER_CONCURRENCY_STORAGE_FAILURES_TOTAL = Counter(
    "bab_provider_concurrency_storage_failures_total",
    "Provider concurrency storage failures.",
    ("backend",),
)
PROVIDER_CONCURRENCY_RENEWAL_LOSSES_TOTAL = Counter(
    "bab_provider_concurrency_renewal_losses_total",
    "Provider concurrency permit renewal ownership losses.",
    ("backend",),
)
PROVIDER_CONCURRENCY_WAIT_SECONDS = Histogram(
    "bab_provider_concurrency_wait_seconds",
    "Provider concurrency wait duration in seconds.",
    ("backend", "outcome"),
)


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    labels = {
        "method": _label(method, UNKNOWN),
        "route": _label(route, UNKNOWN),
        "status_class": status_class(status_code),
        "outcome": outcome_for_status(status_code),
    }
    _best_effort(lambda: HTTP_REQUESTS_TOTAL.labels(**labels).inc())
    _best_effort(lambda: HTTP_REQUEST_DURATION_SECONDS.labels(**labels).observe(duration_seconds))


def record_gateway_request_finalized(
    *,
    gateway_endpoint: str | None,
    status_code: int,
    error_code: str | None,
) -> None:
    labels = {
        "gateway_endpoint": _label(gateway_endpoint, UNKNOWN),
        "status_class": status_class(status_code),
        "outcome": outcome_for_status(status_code),
        "error_code": _label(error_code, NONE),
    }
    _best_effort(lambda: GATEWAY_REQUESTS_TOTAL.labels(**labels).inc())


def record_gateway_route_attempt_finalized(
    *,
    status_code: int | None,
    status: str,
    error_code: str | None,
    duration_seconds: float | None,
) -> None:
    labels = {
        "status": _label(status, UNKNOWN),
        "status_class": _status_class_or_unknown(status_code),
        "outcome": _outcome_or_unknown(status_code),
        "error_code": _label(error_code, NONE),
    }
    _best_effort(lambda: GATEWAY_ROUTE_ATTEMPTS_TOTAL.labels(**labels).inc())
    if duration_seconds is not None:
        _best_effort(
            lambda: GATEWAY_ROUTE_ATTEMPT_DURATION_SECONDS.labels(**labels).observe(
                duration_seconds
            )
        )


def record_gateway_provider_attempt(
    *,
    gateway_endpoint: str,
    status_code: int | None,
    error_code: str | None,
    duration_seconds: float | None,
) -> None:
    labels = {
        "gateway_endpoint": _label(gateway_endpoint, UNKNOWN),
        "status_class": _status_class_or_unknown(status_code),
        "outcome": _outcome_or_unknown(status_code),
        "error_code": _label(error_code, NONE),
    }
    _best_effort(lambda: GATEWAY_PROVIDER_ATTEMPTS_TOTAL.labels(**labels).inc())
    if duration_seconds is not None:
        _best_effort(
            lambda: GATEWAY_PROVIDER_ATTEMPT_DURATION_SECONDS.labels(**labels).observe(
                duration_seconds
            )
        )


def record_gateway_denial(
    *,
    denial_type: str,
    gateway_endpoint: str | None = None,
    phase: str | None = None,
) -> None:
    labels = {
        "denial_type": _label(denial_type, UNKNOWN),
        "gateway_endpoint": _label(gateway_endpoint, UNKNOWN),
        "phase": _label(phase, UNKNOWN),
    }
    _best_effort(lambda: GATEWAY_DENIALS_TOTAL.labels(**labels).inc())


def record_rate_limit_rejection(*, route_group: str, bucket_type: str) -> None:
    labels = {
        "route_group": _label(route_group, UNKNOWN),
        "bucket_type": _label(bucket_type, UNKNOWN),
    }
    _best_effort(lambda: RATE_LIMIT_REJECTIONS_TOTAL.labels(**labels).inc())


def record_provider_circuit_transition(
    *,
    from_state: str,
    to_state: str,
    reason: str,
    backend: str,
) -> None:
    _best_effort(
        lambda: PROVIDER_CIRCUIT_TRANSITIONS_TOTAL.labels(
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            backend=backend,
        ).inc()
    )


def record_provider_circuit_rejection(*, backend: str) -> None:
    _best_effort(lambda: PROVIDER_CIRCUIT_REJECTIONS_TOTAL.labels(backend=backend).inc())


def record_provider_circuit_storage_failure(*, backend: str) -> None:
    _best_effort(
        lambda: PROVIDER_CIRCUIT_STORAGE_FAILURES_TOTAL.labels(backend=backend).inc()
    )


def record_provider_concurrency_rejection(*, backend: str, reason: str) -> None:
    _best_effort(
        lambda: PROVIDER_CONCURRENCY_REJECTIONS_TOTAL.labels(
            backend=backend,
            reason=reason,
        ).inc()
    )


def record_provider_concurrency_storage_failure(*, backend: str) -> None:
    _best_effort(
        lambda: PROVIDER_CONCURRENCY_STORAGE_FAILURES_TOTAL.labels(backend=backend).inc()
    )


def record_provider_concurrency_renewal_loss(*, backend: str) -> None:
    _best_effort(
        lambda: PROVIDER_CONCURRENCY_RENEWAL_LOSSES_TOTAL.labels(backend=backend).inc()
    )


def record_provider_concurrency_wait(
    *,
    backend: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    _best_effort(
        lambda: PROVIDER_CONCURRENCY_WAIT_SECONDS.labels(
            backend=backend,
            outcome=outcome,
        ).observe(duration_seconds)
    )


def metrics_response() -> Response:
    return Response(content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


def _label(value: str | None, default: str) -> str:
    return value if value else default


def _status_class_or_unknown(status_code: int | None) -> str:
    return status_class(status_code) if status_code is not None else UNKNOWN


def _outcome_or_unknown(status_code: int | None) -> str:
    return outcome_for_status(status_code) if status_code is not None else UNKNOWN


def _best_effort(record: Callable[[], None]) -> None:
    try:
        record()
    except Exception:
        return
