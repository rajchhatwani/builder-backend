"""Job settings read from the environment (generated). A bad value stops the process: never a silent default.

    JOBS_POLL_INTERVAL_SECONDS     how long an idle worker waits before looking again (default 1)
    JOBS_LEASE_GRACE_SECONDS       a job's lease is its timeout plus this (default 30)
    JOBS_RETENTION_DAYS            succeeded jobs are deleted after this many days (default 14)
    JOBS_CONCURRENCY               overrides the group's concurrency for this process
    JOBS_SCHEDULER_ENABLED         false keeps a worker from firing schedules (default true)
    JOBS_SCHEDULER_TICK_SECONDS    how often schedules are checked (default 15; tests use less)
    JOBS_SCHEDULER_GRACE_SECONDS   for `missed: skip`: a tick older than this is dropped (default 120)
"""

import os

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")

BACKOFF_CAP_SECONDS = 3600.0
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_ERROR_CHARS = 300


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


def poll_interval() -> float:
    return _number("JOBS_POLL_INTERVAL_SECONDS", 1.0, 0.02, 3600.0)


def lease_grace() -> float:
    return _number("JOBS_LEASE_GRACE_SECONDS", 30.0, 1.0, 3600.0)


def retention_days() -> int:
    return int(_number("JOBS_RETENTION_DAYS", 14, 1, 3650))


def fire_retention_days() -> int:
    """How long `jb_schedule_fires` rows are kept (the newest row of each schedule always stays)."""
    return int(_number("JOBS_SCHEDULE_FIRE_RETENTION_DAYS", 30, 1, 3650))


def concurrency(default: int) -> int:
    return int(_number("JOBS_CONCURRENCY", float(default), 1, 256))


def scheduler_enabled() -> bool:
    return _flag("JOBS_SCHEDULER_ENABLED", True)


def scheduler_tick() -> float:
    return _number("JOBS_SCHEDULER_TICK_SECONDS", 15.0, 0.05, 3600.0)


def scheduler_grace() -> float:
    return _number("JOBS_SCHEDULER_GRACE_SECONDS", 120.0, 1.0, 86400.0)
