"""Event settings read from the environment (generated). A bad value stops the process: never a silent default."""

import os

from app.events import definitions

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")

# Retry schedule: BACKOFF_BASE * 2 ** (attempt - 1) seconds, at most BACKOFF_CAP.
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_CAP_SECONDS = 300.0
PURGE_EVERY_SECONDS = 3600.0


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be true or false")


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def relay_enabled() -> bool:
    """EVENTS_RELAY_ENABLED=false keeps the relay out of the API process (run `python -m app.events.relay`)."""
    return _flag("EVENTS_RELAY_ENABLED", True)


def poll_interval() -> float:
    return _number("EVENTS_POLL_INTERVAL_SECONDS", 1.0, 0.05, 3600.0)


def max_attempts() -> int:
    """After this many failed deliveries an event is parked as `failed` (and blocks its record)."""
    return int(_number("EVENTS_MAX_ATTEMPTS", 8, 1, 1000))


def handler_timeout() -> float:
    return _number("EVENTS_HANDLER_TIMEOUT_SECONDS", 30.0, 0.1, 3600.0)


def retention_days() -> int:
    return int(_number("EVENTS_RETENTION_DAYS", float(definitions.RETENTION_DAYS), 1, 3650))
