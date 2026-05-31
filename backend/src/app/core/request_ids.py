from structlog.contextvars import get_contextvars


def current_request_id() -> str | None:
    value = get_contextvars().get("request_id")
    return str(value) if value else None
