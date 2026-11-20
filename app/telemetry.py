"""OpenTelemetry setup: traces, metrics and logs, all exported over OTLP to the Collector.

Switched on with OTEL_ENABLED=true. Everything else uses the standard OpenTelemetry environment variables:

    OTEL_SERVICE_NAME=boutique-api
    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    OTEL_METRIC_EXPORT_INTERVAL=5000        (milliseconds)

Signals produced
  traces  FastAPI server spans + SQLAlchemy spans (auto-instrumentation) + manual business spans (app/tracing.py)
  metrics HTTP server metrics (auto) + business metrics and inventory gauges (app/metrics.py)
  logs    Python `boutique.*` loggers -> OTLP; every line carries trace_id/span_id for trace-to-log correlation
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import metrics as app_metrics

APP_LOGGER = "boutique"
LOG_FORMAT = "%(message)s trace_id=%(trace_id)s span_id=%(span_id)s"
CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: " + LOG_FORMAT
EXCLUDED_URLS = "health,docs,redoc,openapi.json"  # no spans for probes and the docs pages
TRACE_HEADER = "X-Trace-Id"


SENSITIVE_QUERY = re.compile(r"(?P<key>customer_email|email)=[^&\s]*", re.IGNORECASE)
URL_ATTRIBUTES = ("http.url", "http.target", "url.full", "url.query")


def redact_span(span: ReadableSpan) -> ReadableSpan:
    """Return `span` with personal data removed from its URL attributes (or the same span if it is clean)."""
    attributes = dict(span.attributes or {})
    changed = False
    for key in URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str) and SENSITIVE_QUERY.search(value):
            attributes[key] = SENSITIVE_QUERY.sub(r"\g<key>=REDACTED", value)
            changed = True
    if not changed:
        return span
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanExporter(SpanExporter):
    """Wrap an exporter so personal data never leaves the process inside a span.

    `GET /orders?customer_email=...` would otherwise ship a customer's address to the trace store through
    the auto-instrumented `http.url` attribute. This has to happen at export time: the instrumentation
    rewrites that attribute when the request finishes, which would undo any redaction done at span start.
    """

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner

    def export(self, spans: Any) -> SpanExportResult:
        return self.inner.export([redact_span(span) for span in spans])

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def telemetry_enabled() -> bool:
    return os.getenv("OTEL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


class TraceContextFilter(logging.Filter):
    """Copy the active trace/span id onto each log record so formatters can print it."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = format(context.trace_id, "032x") if context.is_valid else "-"
        record.span_id = format(context.span_id, "016x") if context.is_valid else "-"
        return True


def configure_logging() -> None:
    """Console logging for the `boutique.*` loggers (idempotent)."""
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    if any(getattr(handler, "_boutique_console", False) for handler in logger.handlers):
        return
    console = logging.StreamHandler()
    console._boutique_console = True  # type: ignore[attr-defined]
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    console.addFilter(TraceContextFilter())
    logger.addHandler(console)


class TraceIdHeaderMiddleware:
    """Return the trace id to the caller as `X-Trace-Id`, so any single request can be found in Tempo and Loki.

    It sits *inside* the OpenTelemetry server middleware, so the active span is the request's own span.
    URLs excluded from tracing (e.g. /health) have no active span and therefore get no header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                context = trace.get_current_span().get_span_context()
                if context.is_valid:
                    MutableHeaders(scope=message).append(TRACE_HEADER, format(context.trace_id, "032x"))
            await send(message)

        await self.app(scope, receive, send_with_trace_id)


@dataclass
class TelemetryHandles:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider

    def shutdown(self) -> None:
        """Flush whatever is still buffered, then stop the exporters."""
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def setup_telemetry(
    app: FastAPI,
    *,
    session_factory: Any = None,
    span_processors: list | None = None,
    metric_readers: list | None = None,
    log_processors: list | None = None,
) -> TelemetryHandles:
    """Install the OpenTelemetry SDK and instrument `app`. Call once per process.

    The three `*_processors/readers` arguments default to OTLP exporters; tests pass in-memory ones.
    """
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "boutique-api"),
            "service.version": app.version,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    for processor in span_processors if span_processors is not None else [BatchSpanProcessor(RedactingSpanExporter(OTLPSpanExporter()))]:
        tracer_provider.add_span_processor(processor)
    trace.set_tracer_provider(tracer_provider)

    readers = metric_readers if metric_readers is not None else [PeriodicExportingMetricReader(OTLPMetricExporter())]
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    for processor in log_processors if log_processors is not None else [BatchLogRecordProcessor(OTLPLogExporter())]:
        logger_provider.add_log_record_processor(processor)
    set_logger_provider(logger_provider)

    # Logs: the OTLP handler's formatter puts trace_id/span_id into the log *text* as well as into the
    # structured trace fields, which gives Loki and Grafana an unambiguous key to join on.
    configure_logging()
    otlp_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    otlp_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    otlp_handler.addFilter(TraceContextFilter())
    logging.getLogger(APP_LOGGER).addHandler(otlp_handler)

    app_metrics.inventory_source.session_factory = session_factory

    app.add_middleware(TraceIdHeaderMiddleware)  # added first, so the OTel server middleware wraps it
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=EXCLUDED_URLS,
        exclude_spans=["receive", "send"],  # keep traces readable: no per-ASGI-message spans
    )
    return TelemetryHandles(tracer_provider, meter_provider, logger_provider)


def instrument_engines(*engines: Any) -> None:
    """Emit one span per SQL statement for the given SQLAlchemy engines."""
    SQLAlchemyInstrumentor().instrument(engines=list(engines))


def init_observability(app: FastAPI, engine: Any, session_factory: Any) -> TelemetryHandles | None:
    """Entry point used by app.main: does nothing unless OTEL_ENABLED=true."""
    configure_logging()
    if not telemetry_enabled():
        return None
    handles = setup_telemetry(app, session_factory=session_factory)
    instrument_engines(engine)
    return handles
