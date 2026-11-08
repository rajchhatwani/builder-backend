# Observability of Vault

Generated from the spec. This service emits **traces** and **metrics** with OpenTelemetry and writes
**logs** as JSON on stdout, each carrying the id of the trace it belongs to.

## What is collected

| Signal | What | Where it comes from |
|---|---|---|
| Traces | one server span per request, named after the route template (`GET /items/{item_id}`) | FastAPI instrumentation |
| Traces | one span per Redis command | Redis instrumentation |
| Logs | JSON lines with `trace_id`, `span_id` and `request_id` | structlog |

Not collected: request or response bodies, headers, cookies, SQL parameter values. Paths excluded from tracing:
`/health`, `/ready`.

## Run it locally

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to your collector or backend. The spec was generated without the local
stack (`local_stack: false`).

## Configuration (environment variables only)

| Variable | Default | Meaning |
|---|---|---|
| `APP_OTEL_ENABLED` | `true` | Kill switch. `false` and the module does nothing. |
| `OTEL_SERVICE_NAME` | `vault-api` | Name shown in the backend. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Collector address, e.g. `http://otel-collector:4318`. Empty: nothing leaves the process. |
| `OTEL_EXPORTER_OTLP_HEADERS` | empty | Credentials for a hosted backend. **Secret**: environment only, never in a file. |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Parent-based: if the caller already decided, that decision is followed. |
| `OTEL_TRACES_SAMPLER_ARG` | `0.1` | Share of new traces kept (0 to 1). |
| `OTEL_RESOURCE_ATTRIBUTES` | empty | Extra labels (`region=eu-west-1,team=billing`). |

Changing the amount of data (sampling, batching) never needs a code change.

## Sizing and cost

Rule of thumb used by the builder: a backend that takes about 200 spans per second per small
collector, and about 4 spans per request (one server span plus a few SQL statements).
Tell the builder your expected peak requests per second to get a suggested sample ratio.
Metrics are cheap (one series per route and status) and are not sampled. Errors are the traces you most
want: for production use a **tail-sampling** collector (stanza in `otel-collector.yaml`) that keeps every
error and slow trace and samples the rest.

## Redaction

Two layers. The service scrubs every span before export (`RedactingExporter`): values under
secret-sounding keys (password, token, authorization, cookie, api key, ...), the shapes secrets have (JWTs,
bearer tokens, provider keys, passwords inside URLs) and every query-string value. The collector repeats
the pattern masking and deletes header attributes. Redaction is a safety net: do not log secrets on purpose.

## Limits (known)

* Logs are not exported over OTLP; ship the JSON stdout with your platform's log collector. They correlate by `trace_id`.
* The built-in sampler is head-based. Tail sampling needs a collector that sees whole traces.
* Only the instrumentations listed above are on. Add more in `app/core/telemetry.py`.
