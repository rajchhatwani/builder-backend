"""Validation for the `events` section (transactional outbox + event bus). Issues go through
`add(path, code, message)`. Nothing here runs anything: it checks shape and supported values."""

from collections.abc import Callable

from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

EV_TABLES = ("ev_handled", "ev_outbox")
ADAPTERS = ("in_process", "redis_streams")
# Adapters that are accepted by the schema but have no working implementation yet.
NOT_YET_IMPLEMENTED = ("redis_streams",)
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650


def events_active(spec: Spec) -> bool:
    return spec.events is not None and spec.events.enabled


def check_events(spec: Spec, add: Add) -> None:
    ev = spec.events
    if ev is None or not ev.enabled:
        return
    if ev.adapter not in ADAPTERS:
        add("events.adapter", "unknown_adapter", f"adapter must be one of: {', '.join(ADAPTERS)}")
    elif ev.adapter in NOT_YET_IMPLEMENTED:
        add(
            "events.adapter",
            "not_yet_implemented",
            f"the {ev.adapter} adapter is not implemented yet: use in_process "
            "(the adapter interface is generated so it can be added later)",
        )
    if isinstance(ev.retention_days, bool) or not (
        MIN_RETENTION_DAYS <= ev.retention_days <= MAX_RETENTION_DAYS
    ):
        add(
            "events.retention_days",
            "invalid_value",
            f"retention_days must be {MIN_RETENTION_DAYS} to {MAX_RETENTION_DAYS}",
        )
    if not spec.entities:
        add("events", "no_entities", "events need at least one entity to publish events for")
