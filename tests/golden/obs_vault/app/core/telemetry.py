"""OpenTelemetry for this service (generated). See docs/OBSERVABILITY.md.

Traces and metrics leave over OTLP/HTTP; logs stay structured JSON on stdout (twelve-factor) and
carry the trace id, so a log line and its trace find each other. All tuning is environment variables:

  APP_OTEL_ENABLED             true / false. A kill switch: false makes this module do nothing.
  OTEL_SERVICE_NAME            default 'vault-api'
  OTEL_EXPORTER_OTLP_ENDPOINT  where the collector listens (http://otel-collector:4318). Empty means
                               nothing leaves the process (spans still exist for log correlation).
  OTEL_EXPORTER_OTLP_HEADERS   credentials for a hosted backend. A secret: set it in the environment only.
  OTEL_TRACES_SAMPLER          default parentbased_traceidratio
  OTEL_TRACES_SAMPLER_ARG      share of new traces kept, default 0.1
  OTEL_RESOURCE_ATTRIBUTES     extra resource attributes (team=..., region=...)

Nothing secret reaches a span: every span passes through `RedactingExporter` before it is exported,
which hides values stored under secret-sounding keys, the shapes secrets have (tokens, keys, JWTs,
passwords inside URLs) and every query-string value. Request and response bodies and headers are never
recorded. SQL statements are recorded with placeholders ($1, $2), never with the values bound to them.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Status

from app.core import redact

logger = structlog.get_logger()

DEFAULT_SERVICE_NAME = 'vault-api'
DEFAULT_SAMPLE_RATIO = 0.1
# Paths that never produce spans (probes and the like), matched exactly.
EXCLUDED_PATHS: tuple[str, ...] = ("/health", "/ready")
# Added to the built-in secret keys of app/core/redact.py (substring match, case-insensitive).
EXTRA_REDACT_KEYS: tuple[str, ...] = ()
DB_SPANS = False

_QUERY_VALUE_RE = re.compile(r"([?&][^=&#\s]+)=([^&#\s]*)")
_TRUE = {"1", "true", "yes", "on"}

redact.register_secret_keys(EXTRA_REDACT_KEYS)


def _excluded_urls_pattern() -> str | None:
    """Regexes (comma separated) the instrumentation matches against the full request URL."""
    patterns = [rf"(?:^|://[^/]+){re.escape(path)}(?:\?.*)?$" for path in EXCLUDED_PATHS]
    return ",".join(patterns) or None


def enabled() -> bool:
    return os.environ.get("APP_OTEL_ENABLED", "true").strip().lower() in _TRUE


def _endpoint_configured() -> bool:
    return any(
        os.environ.get(name, "").strip()
        for name in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        )
    )


# -- redaction ------------------------------------------------------------------------------


def mask_query(text: str) -> str:
    """Keep the names of query parameters, drop their values (tokens travel in query strings)."""
    return _QUERY_VALUE_RE.sub(r"\1=" + redact.REDACTED, text) if "?" in text else text


def _clean_value(key: str, value: Any) -> Any:
    if redact.is_secret_key(key):
        return redact.REDACTED
    if isinstance(value, str):
        return mask_query(redact.scrub_text(value))
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return tuple(_clean_value(key, item) for item in value)
    return value


def clean_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: _clean_value(key, value) for key, value in (attributes or {}).items()}


def scrub_span(span: ReadableSpan) -> ReadableSpan:
    """A copy of `span` with secrets removed from its name, attributes, events and status."""
    status = span.status
    if status.description:
        status = Status(status.status_code, redact.scrub_text(status.description))
    return ReadableSpan(
        name=mask_query(redact.scrub_text(span.name)),
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=clean_attributes(span.attributes),
        events=tuple(
            Event(
                name=event.name,
                attributes=clean_attributes(event.attributes),
                timestamp=event.timestamp,
            )
            for event in span.events
        ),
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingExporter(SpanExporter):
    """Wraps a span exporter so every span is scrubbed on its way out."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([scrub_span(span) for span in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


# -- logs and counters ----------------------------------------------------------------------

_counters: dict[str, Any] = {}
_meter: metrics.Meter | None = None
# Log events that are also counted (low-cardinality attributes only).
_COUNTED_EVENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "authz_denied": ("app.authz.denied", ("entity", "op")),
}


def count(name: str, **attributes: str) -> None:
    """Add one to a counter. A no-op while metrics are off."""
    if _meter is None:
        return
    counter = _counters.get(name)
    if counter is None:
        counter = _counters[name] = _meter.create_counter(name)
    counter.add(1, attributes)


def trace_context_processor(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: put the current trace and span ids on every log line, tag the span
    with the request id, and count the events listed in _COUNTED_EVENTS."""
    span = trace.get_current_span()
    context = span.get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
        request_id = event_dict.get("request_id")
        if request_id and span.is_recording():
            span.set_attribute("app.request_id", str(request_id))
    counted = _COUNTED_EVENTS.get(str(event_dict.get("event")))
    if counted is not None:
        name, keys = counted
        count(name, **{k: str(event_dict[k]) for k in keys if k in event_dict})
    return event_dict


def _install_log_processor() -> None:
    config = structlog.get_config()
    processors = list(config["processors"])
    if trace_context_processor in processors:
        return
    # After merge_contextvars (so request_id is present) and before redaction/rendering.
    position = 1 if processors else 0
    processors.insert(position, trace_context_processor)
    structlog.configure(processors=processors)


# -- setup ----------------------------------------------------------------------------------


@dataclass
class Telemetry:
    """What `setup` started, so it can be flushed and stopped (and so tests can inspect it)."""

    active: bool
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    app: Any = None

    def shutdown(self) -> None:
        global _meter
        if not self.active:
            return
        if self.app is not None:
            FastAPIInstrumentor.uninstrument_app(self.app)
        RedisInstrumentor().uninstrument()
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()
        if self.meter_provider is not None:
            self.meter_provider.shutdown()
        _meter = None
        _counters.clear()


_current = Telemetry(active=False)


def setup(
    app: Any,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> Telemetry:
    """Instrument `app` and the database driver. Safe to call once per process.

    `span_exporter` and `metric_reader` replace the OTLP ones (tests; a custom backend).
    """
    global _current, _meter
    if not enabled():
        logger.info("telemetry_disabled")
        _current = Telemetry(active=False)
        return _current

    os.environ.setdefault("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")
    os.environ.setdefault("OTEL_TRACES_SAMPLER_ARG", str(DEFAULT_SAMPLE_RATIO))
    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME,
            "deployment.environment.name": os.environ.get("APP_ENV", "development"),
        }
    )

    exporter: SpanExporter | None = span_exporter
    if exporter is None and _endpoint_configured():
        exporter = OTLPSpanExporter()
    tracer_provider = TracerProvider(resource=resource)  # sampler comes from OTEL_TRACES_SAMPLER*
    if exporter is not None:
        redacting = RedactingExporter(exporter)
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(redacting) if span_exporter is not None else BatchSpanProcessor(redacting)
        )

    meter_provider: MeterProvider | None = None

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=_excluded_urls_pattern(),
    )
    RedisInstrumentor().instrument(tracer_provider=tracer_provider)
    _install_log_processor()
    if exporter is None:
        logger.info("telemetry_local_only", hint="set OTEL_EXPORTER_OTLP_ENDPOINT to export")
    _current = Telemetry(
        active=True, tracer_provider=tracer_provider, meter_provider=meter_provider, app=app
    )
    return _current


def shutdown() -> None:
    """Flush and stop what `setup` started (called when the application stops)."""
    _current.shutdown()
