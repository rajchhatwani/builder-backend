"""Write lifecycle: the fixed order in which every create / update / delete runs.

    before_save -> guards/access -> validate -> write -> after_save -> commit -> after_commit

* before_save: hooks may adjust `ctx.values` (nothing is written yet).
* guards/access (the access policy) and then validate (references, files): the repository's own
  checks. Access runs first so a caller who may not write learns nothing about other records.
* write: the row is added / changed and flushed, still inside the transaction.
* after_save: hooks run inside the transaction. An error or timeout rolls the write back.
* commit.
* after_commit: hooks run after the data is safe. An error or timeout is logged and never fails the
  request (resilience default), because the write already happened.

Every hook is bounded by a timeout (HOOK_TIMEOUT_SECONDS). Hooks are registered per repository in
`hooks`: {stage: (async callable(ctx), ...)}; stages without hooks cost nothing.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.errors import AppError

logger = structlog.get_logger()

STAGES = ("before_save", "after_save", "after_commit")
# Everything the chain does, in order. `guards` and `validate` are the repository's built-in checks.
ORDER = ("before_save", "guards", "validate", "write", "after_save", "commit", "after_commit")
HOOK_TIMEOUT_SECONDS = 5.0


@dataclass
class HookContext:
    entity: str
    op: str  # create | update | replace | delete
    values: dict[str, Any] = field(default_factory=dict)
    item: Any = None
    caller: Any = None
    trace: list[str] = field(default_factory=list)  # stages reached, in order (used by tests)


Hook = Callable[[HookContext], Awaitable[None]]


async def run_stage(
    stage: str,
    hooks: dict[str, tuple[Hook, ...]],
    ctx: HookContext,
    *,
    fail_closed: bool = True,
    timeout: float | None = None,
) -> None:
    """Record the stage, then run its hooks in order. fail_closed=False (after_commit) only logs."""
    ctx.trace.append(stage)
    for hook in hooks.get(stage, ()):
        try:
            await asyncio.wait_for(hook(ctx), timeout or HOOK_TIMEOUT_SECONDS)
        except Exception as exc:
            if not fail_closed:
                logger.error(
                    "lifecycle_hook_failed", stage=stage, entity=ctx.entity, error=type(exc).__name__
                )
                continue
            if isinstance(exc, AppError):
                raise
            raise AppError(
                "hook_failed", f"{stage} hook failed ({type(exc).__name__})", 500
            ) from exc
