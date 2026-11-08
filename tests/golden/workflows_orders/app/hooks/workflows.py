"""Your workflow step functions. Written once; the platform never overwrites this file.

Each hook step needs a function registered under (workflow, step); each step with `compensate` needs an
undo function too:

    from app.workflows.registry import StepContext, compensation, step

    @step("workflow_name", "step_name")
    async def do_it(ctx: StepContext) -> dict | None:
        ...   # ctx.input, ctx.results, ctx.idempotency_key, ctx.attempt; return a JSON result to keep it

    @compensation("workflow_name", "step_name")
    async def undo_it(ctx: StepContext) -> None:
        ...   # ctx.result is what the step returned; ctx.reason is failure or cancel

A function runs at least once: make the work idempotent (key on ctx.idempotency_key). Raise to fail the
attempt (retried with backoff, then the workflow's failure policy applies). Do not log ctx.input as a
whole. A worker refuses to start while a declared function is missing here.
"""

from app.workflows.registry import StepContext, compensation, step


@step('order_flow', 'reserve_stock')
async def order_flow__reserve_stock(ctx: StepContext) -> dict[str, object] | None:
    # order_flow step 1: reserve_stock (3 attempt(s), timeout 30s)
    raise NotImplementedError("write the reserve_stock step of order_flow in app/hooks/workflows.py")


@compensation('order_flow', 'reserve_stock')
async def order_flow__reserve_stock__undo(ctx: StepContext) -> None:
    raise NotImplementedError("write the undo of reserve_stock in order_flow in app/hooks/workflows.py")


@step('order_flow', 'charge_card')
async def order_flow__charge_card(ctx: StepContext) -> dict[str, object] | None:
    # order_flow step 2: charge_card (3 attempt(s), timeout 60s)
    raise NotImplementedError("write the charge_card step of order_flow in app/hooks/workflows.py")


@compensation('order_flow', 'charge_card')
async def order_flow__charge_card__undo(ctx: StepContext) -> None:
    raise NotImplementedError("write the undo of charge_card in order_flow in app/hooks/workflows.py")


@step('order_flow', 'send_receipt')
async def order_flow__send_receipt(ctx: StepContext) -> dict[str, object] | None:
    # order_flow step 3: send_receipt (3 attempt(s), timeout 30s)
    raise NotImplementedError("write the send_receipt step of order_flow in app/hooks/workflows.py")


@step('receipt_flow', 'prepare')
async def receipt_flow__prepare(ctx: StepContext) -> dict[str, object] | None:
    # receipt_flow step 1: prepare (3 attempt(s), timeout 30s)
    raise NotImplementedError("write the prepare step of receipt_flow in app/hooks/workflows.py")
