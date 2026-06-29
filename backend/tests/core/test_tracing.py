import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.config import Settings
from app.core.tracing import (
    configure_tracing,
    current_trace_ids,
    get_tracer,
    set_span_attributes,
    start_span,
)


def test_tracing_disabled_does_not_instrument_app() -> None:
    app = FastAPI()
    settings = _settings(otel_enabled=False)

    configure_tracing(app, current_settings=settings)

    assert not getattr(app.state, "otel_instrumented", False)


def test_invalid_otel_exporter_is_rejected() -> None:
    with pytest.raises(ValueError, match="BAB_OTEL_EXPORTER"):
        Settings(
            BAB_SECRET_KEY="changed-secret-key-with-more-than-32-chars",
            BAB_ENCRYPTION_KEY="mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw=",
            BAB_OTEL_EXPORTER="zipkin",
        )


def test_current_trace_ids_are_null_outside_span() -> None:
    assert current_trace_ids() == {"trace_id": None, "span_id": None}


def test_safe_span_attributes_filter_blocked_names() -> None:
    exporter = InMemorySpanExporter()
    app = FastAPI()
    configure_tracing(
        app,
        current_settings=_settings(otel_enabled=True),
        span_exporter=exporter,
    )

    with start_span("test.safe_attributes"):
        ids = current_trace_ids()
        set_span_attributes(
            {
                "bab.gateway.endpoint": "chat_completions",
                "http.route": "/v1/chat/completions",
                "provider_id": "blocked-provider-id",
                "requested_model": "blocked-model",
                "email": "blocked@example.com",
            }
        )

    span = _span_by_name(exporter.get_finished_spans(), "test.safe_attributes")
    assert ids["trace_id"]
    assert ids["span_id"]
    assert span.attributes["bab.gateway.endpoint"] == "chat_completions"
    assert span.attributes["http.route"] == "/v1/chat/completions"
    assert "provider_id" not in span.attributes
    assert "requested_model" not in span.attributes
    assert "email" not in span.attributes


@pytest.mark.asyncio
async def test_enabled_tracing_records_fastapi_request_span() -> None:
    exporter = InMemorySpanExporter()
    app = FastAPI()
    configure_tracing(
        app,
        current_settings=_settings(otel_enabled=True),
        span_exporter=exporter,
    )

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/ping")

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert getattr(app.state, "otel_instrumented", False)
    assert any(span.attributes.get("http.route") == "/ping" for span in spans)


def test_get_tracer_returns_tracer() -> None:
    tracer = get_tracer("tests.core")

    assert tracer is not None


def _settings(*, otel_enabled: bool) -> Settings:
    return Settings.model_construct(
        app_version="0.1.0",
        environment="test",
        otel_enabled=otel_enabled,
        otel_exporter="none",
        otel_otlp_endpoint="http://localhost:4318/v1/traces",
        otel_service_name="bab-backend-test",
    )


def _span_by_name(spans, name: str):
    for span in spans:
        if span.name == name:
            return span
    raise AssertionError(f"span {name!r} not found")
