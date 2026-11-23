"""Job handlers: the registry and the context a handler receives (generated).

Handlers are written in app/hooks/jobs.py (yours, never overwritten):

    from app.jobs.registry import JobContext, handler

    @handler("send_invoice")                 # the job's name in the spec
    async def send_invoice(ctx: JobContext) -> None:   # the function is named by the spec's `handler`
        invoice_id = ctx.payload["invoice_id"]
        ...

* A handler runs at least once per job. While a worker holds the job's lease no other worker runs it, but a
  worker that dies or hangs loses the lease and the job runs again elsewhere: make the work idempotent
  (key on `ctx.job_id`).
* Raise to fail the attempt (it is retried with backoff up to the cap, then parked as `dead`). Only the
  exception's class name is stored. A handler that runs past its timeout is cancelled.
* Never log `ctx.payload` wholesale: it may hold personal data.
"""

import importlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.jobs import definitions

HANDLERS_MODULE = "app.hooks.jobs"


@dataclass(frozen=True)
class JobContext:
    job_id: uuid.UUID
    name: str
    attempt: int  # 1 for the first run
    max_attempts: int
    payload: dict[str, Any]

    @property
    def is_last_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


Handler = Callable[[JobContext], Awaitable[None]]

_HANDLERS: dict[str, Handler] = {}


def handler(job_name: str) -> Callable[[Handler], Handler]:
    """Register the function that runs job `job_name`. Unknown names and mismatched function names are refused."""

    def register(fn: Handler) -> Handler:
        declared = definitions.JOBS.get(job_name)
        if declared is None:
            raise ValueError(f"unknown job {job_name!r}: declare it in the spec first")
        if fn.__name__ != declared["handler"]:
            raise ValueError(
                f"job {job_name!r} is handled by a function named {declared['handler']!r}, not {fn.__name__!r}"
            )
        if job_name in _HANDLERS and _HANDLERS[job_name] is not fn:
            raise ValueError(f"job {job_name!r} already has a handler")
        _HANDLERS[job_name] = fn
        return fn

    return register


def get(job_name: str) -> Handler | None:
    return _HANDLERS.get(job_name)


def clear_handlers() -> None:
    """For tests."""
    _HANDLERS.clear()


def load_handlers() -> None:
    """Import app/hooks/jobs.py and check every declared job has its handler (fail closed: a job
    without code would only fail later, one retry at a time)."""
    importlib.import_module(HANDLERS_MODULE)
    missing = sorted(name for name in definitions.JOBS if name not in _HANDLERS)
    if missing:
        raise RuntimeError(f"no handler registered in {HANDLERS_MODULE} for: {', '.join(missing)}")
