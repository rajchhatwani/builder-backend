"""Workflow settings read from the environment (generated). A bad value stops the process: never a silent default.

    WORKFLOWS_POLL_INTERVAL_SECONDS   how long an idle worker waits before looking again (default 1)
    WORKFLOWS_LEASE_GRACE_SECONDS     a step's lease is its timeout plus this (default 30)
    WORKFLOWS_CONCURRENCY             overrides the declared worker concurrency for this process
    WORKFLOWS_RETENTION_DAYS          finished runs (and their steps) are deleted after this many days (default 90)
"""

import os

BACKOFF_CAP_SECONDS = 3600.0
MAX_INPUT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_ERROR_CHARS = 300


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
    return _number("WORKFLOWS_POLL_INTERVAL_SECONDS", 1.0, 0.02, 3600.0)


def lease_grace() -> float:
    return _number("WORKFLOWS_LEASE_GRACE_SECONDS", 30.0, 1.0, 3600.0)


def concurrency(default: int) -> int:
    return int(_number("WORKFLOWS_CONCURRENCY", float(default), 1, 256))


def retention_days() -> int:
    return int(_number("WORKFLOWS_RETENTION_DAYS", 90, 1, 3650))
