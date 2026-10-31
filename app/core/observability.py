"""Facts about the observability feature that the builder, the generator and the docs share."""

import math
import re

# Python packages of the generated service. The SDK and API move together (1.x); the
# instrumentation packages are versioned 0.<minor>b<n> and each release pins a matching SDK range.
OTEL_SDK_FLOOR = "1.45.1"
OTEL_INSTRUMENTATION_FLOOR = "0.66b1"
OTEL_INSTRUMENTATION_CEILING = "0.67"

# Container images for deploy/observability/ (pinned: a floating tag changes behaviour silently).
COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.163.2"
JAEGER_IMAGE = "jaegertracing/jaeger:2.22.0"
PROMETHEUS_IMAGE = "prom/prometheus:v3.15.1"

SERVICE_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,62}")
PATH_RE = re.compile(r"/[A-Za-z0-9/_.-]{0,100}")
REDACT_KEY_RE = re.compile(r"[a-z][a-z0-9_.-]{1,39}")
MAX_EXCLUDE_PATHS = 20
MAX_REDACT_KEYS = 50

# Spans one backend can take comfortably on one small collector; the advice below keeps a service
# under it. It is a rule of thumb (see docs/OBSERVABILITY.md), not a measurement.
SPAN_BUDGET_PER_SECOND = 200
SPANS_PER_REQUEST = 4  # one server span plus a few SQL spans, typically


def recommended_sample_ratio(expected_rps: int | None) -> float:
    """Share of traces to keep so the service sends at most ~SPAN_BUDGET_PER_SECOND spans/second.

    1.0 for small services (keep everything), falling as traffic grows, never below 1%.
    """
    if expected_rps is None or expected_rps <= 0:
        return 1.0
    ratio = SPAN_BUDGET_PER_SECOND / (expected_rps * SPANS_PER_REQUEST)
    return max(0.01, min(1.0, math.floor(ratio * 100) / 100))


# What app/core/redact.py of a generated project hides by key name (shown in the dashboard).
BUILTIN_REDACT_KEYS = (
    "password",
    "secret",
    "token",
    "authorization",
    "signature",
    "api key",
    "cookie",
    "credential",
    "private key",
    "client secret",
)
