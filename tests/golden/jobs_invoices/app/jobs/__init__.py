"""Background jobs, schedules and worker groups (generated).

    from app.jobs import enqueue

    await enqueue("send_invoice", {"invoice_id": "..."}, session=session)   # joins your transaction

* A job row is written like any other row: with `session=` it commits or rolls back WITH your write, so
  a rolled-back change enqueues nothing. Without `session` it commits on its own.
* Workers (`python -m app.jobs.worker --group NAME`) claim rows with FOR UPDATE SKIP LOCKED under a
  lease; a job's handler (app/hooks/jobs.py, yours) runs at least once and, while its lease is held,
  never at the same time in two workers. Make handlers idempotent (key on `ctx.job_id`).
* A job that keeps failing is retried with backoff up to its cap, then parked as `dead` (see
  `python -m app.jobs.admin list-dead` / `requeue`).
"""

import datetime as _dt
import uuid as _uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession


async def enqueue(
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    session: _AsyncSession | None = None,
    run_at: _dt.datetime | None = None,
    dedupe_key: str | None = None,
    tenant_id: _uuid.UUID | None = None,
) -> _uuid.UUID | None:
    """Add a job. Returns its id, or None when `dedupe_key` is already taken (the job already exists).
    A key is unique per `tenant_id`: pass it in a multi-tenant project."""
    from app.jobs import queue  # imported late: this package is imported while the models are

    return await queue.enqueue(
        name, payload, session=session, run_at=run_at, dedupe_key=dedupe_key, tenant_id=tenant_id
    )
