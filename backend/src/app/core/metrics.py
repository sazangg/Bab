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
