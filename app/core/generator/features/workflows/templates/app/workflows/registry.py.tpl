"""Step functions: the registry and the context a function receives (generated).

The functions are written in app/hooks/workflows.py (yours, never overwritten):

    from app.workflows.registry import StepContext, compensation, step

    @step("order_flow", "reserve_stock")             # workflow name, step name (both from the spec)
    async def reserve_stock(ctx: StepContext) -> dict | None:
        ...                                          # a JSON-able result is kept for later steps

    @compensation("order_flow", "reserve_stock")     # only for a step with `compensate: true`
    async def release_stock(ctx: StepContext) -> None:
        ...                                          # ctx.result is this step's own result

* A function runs at least once: a worker that dies mid-step loses its lease and the step runs again
  elsewhere. Make the work idempotent and key it on `ctx.idempotency_key` (the same for every attempt of
  the same step of the same run). A step that has been recorded is never run again.
* Raise to fail the attempt (retried with backoff up to the step's cap). Only the exception's class name
  is stored. A function that runs past its timeout is cancelled.
* A `job` step has no function here: the platform enqueues the declared job.
* Never log `ctx.input` or results wholesale: they may hold personal data.
"""

import importlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.workflows import definitions

HANDLERS_MODULE = "app.hooks.workflows"


@dataclass(frozen=True)
class StepContext:
    run_id: uuid.UUID
    workflow: str
    step: str
    attempt: int  # 1 for the first run of this step
    max_attempts: int
    input: dict[str, Any]
    results: dict[str, Any]  # the results of the steps recorded so far, by step name
    idempotency_key: str
    tenant_id: uuid.UUID | None
    compensating: bool = False
    reason: str | None = None  # failure | cancel, while compensating
    result: Any = None  # while compensating: the result this step recorded
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_last_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


Handler = Callable[[StepContext], Awaitable[Any]]

_STEPS: dict[tuple[str, str], Handler] = {}
_COMPENSATIONS: dict[tuple[str, str], Handler] = {}


def _declared(workflow: str, name: str) -> dict[str, Any]:
    wf = definitions.WORKFLOWS.get(workflow)
    if wf is None:
        raise ValueError(f"unknown workflow {workflow!r}: declare it in the spec first")
    for declared in wf["steps"]:
        if declared["name"] == name:
            return declared  # type: ignore[no-any-return]
    raise ValueError(f"workflow {workflow!r} has no step {name!r}")


def step(workflow: str, name: str) -> Callable[[Handler], Handler]:
    """Register the function that runs step `name` of `workflow` (hook steps only)."""

    def register(fn: Handler) -> Handler:
        declared = _declared(workflow, name)
        if declared["kind"] != "hook":
            raise ValueError(f"step {name!r} enqueues a job: it has no function")
        if (workflow, name) in _STEPS and _STEPS[(workflow, name)] is not fn:
            raise ValueError(f"step {name!r} of {workflow!r} already has a function")
        _STEPS[(workflow, name)] = fn
        return fn

    return register


def compensation(workflow: str, name: str) -> Callable[[Handler], Handler]:
    """Register the function that undoes step `name` of `workflow`."""

    def register(fn: Handler) -> Handler:
        declared = _declared(workflow, name)
        if not declared["compensate"]:
            raise ValueError(f"step {name!r} is declared without a compensation")
        if (workflow, name) in _COMPENSATIONS and _COMPENSATIONS[(workflow, name)] is not fn:
            raise ValueError(f"step {name!r} of {workflow!r} already has a compensation")
        _COMPENSATIONS[(workflow, name)] = fn
        return fn

    return register


def get_step(workflow: str, name: str) -> Handler | None:
    return _STEPS.get((workflow, name))


def get_compensation(workflow: str, name: str) -> Handler | None:
    return _COMPENSATIONS.get((workflow, name))


def clear_handlers() -> None:
    """For tests."""
    _STEPS.clear()
    _COMPENSATIONS.clear()


def load_handlers() -> None:
    """Import app/hooks/workflows.py and check every declared function exists (fail closed: a step
    without code would only fail later, one retry at a time)."""
    importlib.import_module(HANDLERS_MODULE)
    missing: list[str] = []
    for wf_name, wf in definitions.WORKFLOWS.items():
        for declared in wf["steps"]:
            key = (wf_name, declared["name"])
            if declared["kind"] == "hook" and key not in _STEPS:
                missing.append(f"{wf_name}.{declared['name']}")
            if declared["compensate"] and key not in _COMPENSATIONS:
                missing.append(f"{wf_name}.{declared['name']} (compensation)")
    if missing:
        raise RuntimeError(f"no function registered in {HANDLERS_MODULE} for: {', '.join(sorted(missing))}")
