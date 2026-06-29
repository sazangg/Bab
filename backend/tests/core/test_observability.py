import pytest
from fastapi import Response
from starlette.requests import Request

from app.core import request_context
from app.core.observability import outcome_for_status, safe_path, status_class


def test_observability_status_helpers() -> None:
    assert status_class(200) == "2xx"
    assert status_class(403) == "4xx"
    assert status_class(502) == "5xx"
    assert outcome_for_status(200) == "succeeded"
    assert outcome_for_status(403) == "denied"
    assert outcome_for_status(502) == "failed"
    assert safe_path("/api/v1/health") == "/api/v1/health"


@pytest.mark.asyncio
async def test_request_context_logs_completion_fields(monkeypatch) -> None:
    logger = _FakeLogger()
    monkeypatch.setattr(request_context, "logger", logger)
    request = _request(path="/api/v1/projects/123?secret=nope", route_path="/api/v1/projects/{id}")

    async def call_next(_request):
        return Response(status_code=204)

    response = await request_context.request_context_middleware(request, call_next)

    assert response.headers[request_context.REQUEST_ID_HEADER]
    event_name, fields = logger.infos[-1]
    assert event_name == "request_completed"
    assert fields["method"] == "GET"
    assert fields["path"] == "/api/v1/projects/123"
    assert fields["route"] == "/api/v1/projects/{id}"
    assert fields["status_code"] == 204
    assert fields["status_class"] == "2xx"
    assert fields["outcome"] == "succeeded"
    assert "duration_ms" in fields


@pytest.mark.asyncio
async def test_request_context_logs_failure_fields(monkeypatch) -> None:
    logger = _FakeLogger()
    monkeypatch.setattr(request_context, "logger", logger)
    request = _request(path="/api/v1/fail?token=nope")

    async def call_next(_request):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await request_context.request_context_middleware(request, call_next)

    event_name, fields = logger.exceptions[-1]
    assert event_name == "request_failed"
    assert fields["method"] == "GET"
    assert fields["path"] == "/api/v1/fail"
    assert fields["route"] == "/api/v1/fail"
    assert fields["status_code"] == 500
    assert fields["status_class"] == "5xx"
    assert fields["outcome"] == "failed"
    assert "duration_ms" in fields


def _request(*, path: str, route_path: str | None = None) -> Request:
    clean_path = path.split("?", 1)[0]
    scope = {
        "type": "http",
        "method": "GET",
        "path": clean_path,
        "query_string": path.split("?", 1)[1].encode() if "?" in path else b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }
    if route_path is not None:
        scope["route"] = _Route(route_path)
    return Request(scope)


class _Route:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeLogger:
    def __init__(self) -> None:
        self.infos = []
        self.exceptions = []

    def info(self, event_name: str, **fields) -> None:
        self.infos.append((event_name, fields))

    def exception(self, event_name: str, **fields) -> None:
        self.exceptions.append((event_name, fields))
