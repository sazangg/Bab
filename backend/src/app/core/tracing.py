from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Tracer

from app.core.config import Settings, settings

SAFE_ATTRIBUTE_PREFIXES = ("bab.", "http.")
_tracer_provider: TracerProvider | None = None
_httpx_instrumented_provider: TracerProvider | None = None


def configure_tracing(
    app: FastAPI,
    *,
    current_settings: Settings | None = None,
    span_exporter: SpanExporter | None = None,
) -> None:
    current_settings = current_settings or settings
    if not current_settings.otel_enabled:
        return
    if getattr(app.state, "otel_instrumented", False):
        return

    provider = _build_tracer_provider(current_settings, span_exporter=span_exporter)
    _set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="/metrics,/assets/.*",
    )
    _instrument_httpx(provider)
    app.state.otel_instrumented = True


def get_tracer(name: str) -> Tracer:
    if _tracer_provider is not None:
        return _tracer_provider.get_tracer(name)
    return trace.get_tracer(name)


def current_trace_ids() -> dict[str, str | None]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {"trace_id": None, "span_id": None}
    return {
        "trace_id": f"{span_context.trace_id:032x}",
        "span_id": f"{span_context.span_id:016x}",
    }


def set_span_attributes(attributes: Mapping[str, object | None]) -> None:
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for key, value in _safe_attributes(attributes).items():
        span.set_attribute(key, value)


def add_span_event(name: str, attributes: Mapping[str, object | None] | None = None) -> None:
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.add_event(name, _safe_attributes(attributes or {}))


@contextmanager
def start_span(name: str, attributes: Mapping[str, object | None] | None = None) -> Iterator[Span]:
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span(name, attributes=_safe_attributes(attributes or {})) as span:
        yield span


def _build_tracer_provider(
    current_settings: Settings,
    *,
    span_exporter: SpanExporter | None,
) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create(
            {
                SERVICE_NAME: current_settings.otel_service_name,
                SERVICE_VERSION: current_settings.app_version,
                DEPLOYMENT_ENVIRONMENT: current_settings.environment,
            }
        )
    )
    exporter = span_exporter or _exporter_for(current_settings)
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


def _exporter_for(current_settings: Settings) -> SpanExporter | None:
    if current_settings.otel_exporter == "none":
        return None
    if current_settings.otel_exporter == "console":
        return ConsoleSpanExporter()
    return OTLPSpanExporter(endpoint=current_settings.otel_otlp_endpoint)


def _set_tracer_provider(provider: TracerProvider) -> None:
    global _tracer_provider
    _tracer_provider = provider


def _instrument_httpx(provider: TracerProvider) -> None:
    global _httpx_instrumented_provider
    if _httpx_instrumented_provider is provider:
        return
    instrumentor = HTTPXClientInstrumentor()
    if _httpx_instrumented_provider is not None:
        instrumentor.uninstrument()
    instrumentor.instrument(tracer_provider=provider)
    _httpx_instrumented_provider = provider


def _safe_attributes(attributes: Mapping[str, object | None]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None or not key.startswith(SAFE_ATTRIBUTE_PREFIXES):
            continue
        if isinstance(value, str | bool | int | float):
            safe[key] = value
    return safe
