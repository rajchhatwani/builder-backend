"""Your incoming webhook handlers. Written once; the platform never overwrites this file.

    from app.webhooks.handlers import InboundContext, inbound

    @inbound("endpoint_name")
    async def handle(ctx: InboundContext) -> None:
        event = ctx.json()          # the verified body
        ...                         # write through ctx.session: it commits together with the dedupe record

A handler runs only for a request with a valid signature and a delivery id not seen before. If it raises, nothing
is recorded and the sender's retry runs it again. Do not log the body wholesale.
"""
