import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.metrics import record_http_request
from app.core.observability import outcome_for_status, safe_path, status_class
from app.core.tracing import current_trace_ids

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Baseline security response headers applied to every response (including the
# /assets static mount). nosniff stops MIME-confusion on uploaded assets;
# no-referrer keeps tokens carried in URLs (e.g. accept-invite links) out of the
# Referer header sent to third parties.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _apply_security_headers(response: Response) -> None:
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    clear_contextvars()
    bind_contextvars(request_id=request_id)
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        path = safe_path(request.url.path)
        if path != "/metrics":
            record_http_request(
                method=request.method,
                route=_request_metric_route(request),
                status_code=500,
                duration_seconds=duration_ms / 1000,
            )
        logger.exception(
            "request_failed",
            method=request.method,
            path=path,
            route=_request_route(request, path),
            status_code=500,
            status_class=status_class(500),
            outcome=outcome_for_status(500),
            duration_ms=duration_ms,
            **current_trace_ids(),
        )
        clear_contextvars()
        raise

    duration_ms = round((time.perf_counter() - started_at) * 1000)
    path = safe_path(request.url.path)
    response.headers[REQUEST_ID_HEADER] = request_id
    _apply_security_headers(response)
    if path != "/metrics":
        record_http_request(
            method=request.method,
            route=_request_metric_route(request),
            status_code=response.status_code,
            duration_seconds=duration_ms / 1000,
        )
    logger.info(
        "request_completed",
        method=request.method,
        path=path,
        route=_request_route(request, path),
        status_code=response.status_code,
        status_class=status_class(response.status_code),
        outcome=outcome_for_status(response.status_code),
        duration_ms=duration_ms,
        **current_trace_ids(),
    )
    clear_contextvars()
    return response


def _request_route(request: Request, fallback: str) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else fallback


def _request_metric_route(request: Request) -> str:
    return _request_route(request, "unmatched")
