"""Durable workflows (generated): ordered steps recorded in Postgres, undone in reverse order on failure.

    from app.workflows import start

    run_id = await start("order_flow", {"order_id": "..."}, session=session, tenant_id=tenant_id)

* A run is a row (`wf_runs`); every completed step is a row (`wf_steps`). A worker
  (`python -m app.workflows.worker`) claims a run under a lease and executes it one step at a time. A
  worker that dies loses the lease; another one resumes AFTER the last recorded step. A recorded step is
  never run again. A step that was in flight when the worker died runs again (at least once): key the
  work on `ctx.idempotency_key`, which is the same for every attempt of the same step of the same run.
* The functions are yours, in app/hooks/workflows.py. When a step fails for good (retries used up) the
  completed steps are undone in reverse order by their `compensation` functions (on_failure: compensate),
  or the run stops as `failed` (on_failure: fail). A cancel does the same unwinding.
* With `session=` the run joins the caller's transaction, so a rolled-back write starts nothing.
"""

import uuid as _uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession


async def start(
    workflow: str,
    input: dict[str, Any] | None = None,
    *,
    session: _AsyncSession | None = None,
    tenant_id: _uuid.UUID | None = None,
    created_by: _uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> _uuid.UUID:
    """Start a run and return its id. A `dedupe_key` (unique per tenant and workflow) makes a second start
    return the first run's id instead of creating another."""
    from app.workflows import engine  # imported late: this package is imported while the models are

    return await engine.start(
        workflow, input, session=session, tenant_id=tenant_id, created_by=created_by, dedupe_key=dedupe_key
    )
