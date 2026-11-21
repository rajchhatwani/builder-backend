"""Your job handlers. Written once; the platform never overwrites this file.

Each declared job needs one function, named as in the spec's `handler`, registered under the job's name:

    from app.jobs.registry import JobContext, handler

    @handler("job_name")
    async def the_handler_name(ctx: JobContext) -> None:
        ...   # ctx.payload, ctx.job_id, ctx.attempt

A job runs at least once: make the work idempotent (key on ctx.job_id). Raise to fail the attempt (it is
retried with backoff, then parked as dead). Do not log ctx.payload as a whole. A worker refuses to start
while a declared job has no handler here.
"""

from app.jobs.registry import JobContext, handler
from app.webhooks import worker_job as _webhook_job  # noqa: F401  (the platform's `webhook_delivery` handler)


@handler('send_invoice')
async def send_invoice(ctx: JobContext) -> None:
    # job send_invoice: queue default, 4 attempt(s), timeout 60s
    raise NotImplementedError("write the send_invoice handler in app/hooks/jobs.py")
