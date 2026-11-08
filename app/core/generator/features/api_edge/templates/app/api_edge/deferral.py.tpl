"""after_commit hooks of idempotent requests (generated).

A request with an Idempotency-Key commits late: its business write and the stored response share one
transaction that the middleware commits. The write lifecycle (crud/lifecycle.py) must not run the
`after_commit` stage before that real commit, so while a keyed request is in flight this wrapper
holds the stage back. The middleware runs it once the commit has succeeded, on the first execution
only (a replay never runs a write, so it has nothing to run), and drops it when the request fails.

Same rule as everywhere else: an after_commit error is logged and never fails the request. A crash
between the commit and the hooks means they may not run (at most once per commit); use events (the
outbox) for effects that must not be lost."""

import contextvars
import functools
from typing import Any

from app.api_edge.state import EdgeState
from app.crud import _base, lifecycle

current: contextvars.ContextVar[EdgeState | None] = contextvars.ContextVar("api_edge_current", default=None)
_original = lifecycle.run_stage


async def run_stage(stage: str, hooks: Any, ctx: Any, **options: Any) -> None:
    edge = current.get()
    if stage == "after_commit" and edge is not None and edge.after_commit is not None:
        edge.after_commit.append(functools.partial(_original, stage, hooks, ctx, **options))
        return
    await _original(stage, hooks, ctx, **options)


def install() -> None:
    """Route the write lifecycle through the wrapper. Fails closed if the lifecycle is not as expected."""
    if _base.run_stage is run_stage:
        return
    if _base.run_stage is not _original:
        raise RuntimeError("api_edge: the write lifecycle is not the expected one; refusing to start")
    _base.run_stage = run_stage
