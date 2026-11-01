"""Validation for the `webhooks` section (webhooks out and in). Issues go through `add(path, code, message)`.
Nothing here runs anything: it checks shape, ranges, and that the blocks webhooks stand on are present.
Default deny: a webhook can only announce events the spec lists, and the spec holds no secret."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

WEBHOOK_TABLES = ("wh_attempts", "wh_deliveries", "wh_endpoints", "wh_inbound", "wh_subscriptions")
WEBHOOK_JOB = "webhook_delivery"  # the job (declared in the spec's jobs) that delivers one webhook
NAME_RE = re.compile(r"[a-z][a-z0-9_]{1,39}")
# Ports of services that must never be a webhook target even when the spec lists them: databases, caches,
# brokers, mail, shells, container and cloud control planes.
FORBIDDEN_PORTS = frozenset(
    {
        21, 22, 23, 25, 53, 110, 111, 135, 139, 143, 389, 445, 465, 587, 636, 993, 995, 1433, 1521, 2049,
        2181, 2375, 2376, 2379, 2380, 3306, 3389, 4369, 5432, 5672, 5984, 6379, 6443, 7000, 8086, 9042,
        9092, 9200, 9300, 10250, 11211, 15672, 27017, 50070,
    }
)  # fmt: skip
MAX_EVENTS = 200
MAX_INBOUND = 50
MAX_PORTS = 10


def webhooks_active(spec: Spec) -> bool:
    return spec.webhooks is not None and spec.webhooks.enabled


def _int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _prefix(entity_name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", entity_name).lower()


def event_names(spec: Spec) -> set[str]:
    """Every event name the events block publishes (kept in step with the events feature)."""
    machines = {m.entity for m in spec.state_machines}
    names: set[str] = set()
    for entity in spec.entities:
        prefix = _prefix(entity.name)
        names |= {f"{prefix}.created", f"{prefix}.updated", f"{prefix}.deleted"}
        if entity.name in machines:
            names.add(f"{prefix}.transitioned")
    return names


def check_webhooks(spec: Spec, add: Add) -> None:
    wh = spec.webhooks
    if wh is None or not wh.enabled:
        return
    if spec.auth is None or not spec.auth.enabled:
        add("webhooks", "needs_auth", "the webhook admin API needs auth: enable auth first")
    elif wh.admin_role not in {r.name for r in spec.auth.roles}:
        add("webhooks.admin_role", "unknown_role", f"admin_role {wh.admin_role!r} is not a role of the project")
    if spec.events is None or not spec.events.enabled:
        add("webhooks", "needs_events", "outgoing webhooks are fed by the outbox: enable events first")
    if spec.providers is None or not spec.providers.enabled:
        add("webhooks", "needs_providers", "signing secrets live in the credential vault: enable providers first")
    jobs = spec.jobs
    if jobs is None or not jobs.enabled:
        add("webhooks", "needs_jobs", f"retries run as a job: enable jobs and declare a job {WEBHOOK_JOB!r}")
    else:
        job = next((j for j in jobs.jobs if j.name == WEBHOOK_JOB), None)
        if job is None:
            add(
                "webhooks",
                "needs_delivery_job",
                f"declare a job named {WEBHOOK_JOB!r} with handler {WEBHOOK_JOB!r} (the platform supplies its code)",
            )
        else:
            if job.handler != WEBHOOK_JOB:
                add("jobs.jobs", "webhook_job_handler", f"the handler of job {WEBHOOK_JOB!r} must be {WEBHOOK_JOB!r}")
            if job.timeout_seconds < wh.timeout_seconds + 15:
                add(
                    "jobs.jobs",
                    "webhook_job_timeout",
                    f"the {WEBHOOK_JOB!r} job timeout must be at least webhooks.timeout_seconds + 15",
                )
            if not any(job.queue in g.queues for g in jobs.worker_groups):
                add("jobs.jobs", "webhook_job_queue", f"no worker group serves queue {job.queue!r} of {WEBHOOK_JOB!r}")
    if not spec.entities:
        add("webhooks", "no_entities", "webhooks need at least one entity to announce events for")
    if isinstance(wh.timeout_seconds, bool) or not 1 <= wh.timeout_seconds <= 60:
        add("webhooks.timeout_seconds", "invalid_value", "timeout_seconds must be 1 to 60")
    if not _int(wh.max_consecutive_failures, 1, 100):
        add("webhooks.max_consecutive_failures", "invalid_value", "max_consecutive_failures must be 1 to 100")
    if not _int(wh.secret_overlap_hours, 1, 720):
        add("webhooks.secret_overlap_hours", "invalid_value", "secret_overlap_hours must be 1 to 720")
    if not _int(wh.max_payload_bytes, 1024, 1_048_576):
        add("webhooks.max_payload_bytes", "invalid_value", "max_payload_bytes must be 1024 to 1048576")
    known = event_names(spec)
    if len(wh.events) > MAX_EVENTS:
        add("webhooks.events", "too_many", f"at most {MAX_EVENTS} events")
    seen_events: set[str] = set()
    for i, name in enumerate(wh.events):
        if name not in known:
            add(f"webhooks.events[{i}]", "unknown_event", f"{name!r} is not an event of this project")
        if name in seen_events:
            add(f"webhooks.events[{i}]", "duplicate_event", f"{name!r} is listed twice")
        seen_events.add(name)
    if len(wh.allowed_ports) > MAX_PORTS:
        add("webhooks.allowed_ports", "too_many", f"at most {MAX_PORTS} ports")
    for i, port in enumerate(wh.allowed_ports):
        path = f"webhooks.allowed_ports[{i}]"
        if not _int(port, 1, 65535):
            add(path, "invalid_value", "a port is 1 to 65535")
        elif port in FORBIDDEN_PORTS:
            add(path, "forbidden_port", f"port {port} belongs to an internal service kind and cannot be a webhook target")
    if len(wh.inbound) > MAX_INBOUND:
        add("webhooks.inbound", "too_many", f"at most {MAX_INBOUND} incoming endpoints")
    names: set[str] = set()
    for i, ep in enumerate(wh.inbound):
        path = f"webhooks.inbound[{i}]"
        if not NAME_RE.fullmatch(ep.name):
            add(f"{path}.name", "invalid_name", "name must be lowercase letters, digits and underscores (2-40)")
        if ep.name in names:
            add(f"{path}.name", "duplicate_name", f"{ep.name!r} is listed twice")
        names.add(ep.name)
        if not _int(ep.tolerance_seconds, 30, 3600):
            add(f"{path}.tolerance_seconds", "invalid_value", "tolerance_seconds must be 30 to 3600")
        if not _int(ep.max_body_bytes, 1024, 1_048_576):
            add(f"{path}.max_body_bytes", "invalid_value", "max_body_bytes must be 1024 to 1048576")
        if not _int(ep.dedupe_days, 1, 90):
            add(f"{path}.dedupe_days", "invalid_value", "dedupe_days must be 1 to 90")
