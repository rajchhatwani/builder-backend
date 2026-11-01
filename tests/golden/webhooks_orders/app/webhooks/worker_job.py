"""The handler of the `webhook_delivery` job (generated). Imported by app/hooks/jobs.py."""

from app.jobs.registry import JobContext, handler
from app.webhooks import delivery


@handler("webhook_delivery")
async def webhook_delivery(ctx: JobContext) -> None:
    await delivery.run_job(ctx.job_id, ctx.payload, ctx.attempt, ctx.is_last_attempt)
