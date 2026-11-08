"""Notification settings read from the environment (generated).

NOTIFICATIONS_DISPATCHER_ENABLED  `false` leaves sending to `python -m app.notifications.dispatcher`
                                  (default true: the API process sends).
NOTIFICATIONS_POLL_SECONDS        how often the dispatcher looks for due messages (default 2).
NOTIFICATIONS_LEASE_SECONDS       how long one claimed message is held before another dispatcher may take it
                                  over (default 300).
"""

import os

PURGE_EVERY_SECONDS = 3600.0
BATCH = 20


def _number(name: str, default: float, low: float, high: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a number") from None
    if not low <= value <= high:
        raise RuntimeError(f"{name} must be between {low:g} and {high:g}")
    return value


def dispatcher_enabled() -> bool:
    return os.environ.get("NOTIFICATIONS_DISPATCHER_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def poll_seconds() -> float:
    return _number("NOTIFICATIONS_POLL_SECONDS", 2.0, 0.05, 3600.0)


def lease_seconds() -> float:
    return _number("NOTIFICATIONS_LEASE_SECONDS", 300.0, 5.0, 86_400.0)
