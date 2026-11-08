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


@handler('send_receipt_email')
async def send_receipt_email(ctx: JobContext) -> None:
    # job send_receipt_email: queue default, 3 attempt(s), timeout 60s
    raise NotImplementedError("write the send_receipt_email handler in app/hooks/jobs.py")
