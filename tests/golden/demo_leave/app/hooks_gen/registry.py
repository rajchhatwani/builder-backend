"""Custom hooks wired into the lifecycle chain and the state-machine guards (generated from the spec).

Change a hook in the builder, never here. The logic lives in app/custom/hooks/<name>.py.
"""

from typing import Any

from app.crud.lifecycle import Hook, HookContext
from app.custom.hooks.check_request import check_request as _fn_check_request
from app.hooks_gen import contracts, runtime

DEFINITIONS: dict[str, dict[str, Any]] = {'check_request': {'cpu_ms': 200,
                   'entity': 'LeaveRequest',
                   'enums': {},
                   'fallback': None,
                   'input_fields': ['days', 'reason'],
                   'kind': 'pure',
                   'name': 'check_request',
                   'outbound_calls': 0,
                   'output_fields': ['valid', 'message'],
                   'point': 'LeaveRequest.validate',
                   'policy': 'fail_closed',
                   'reads': [],
                   'rows': 0,
                   'stage': 'validate',
                   'transition': None}}

_CODE: dict[str, tuple[Any, Any, Any]] = {
    "check_request": (_fn_check_request, contracts.RequestInput, contracts.RequestResult),
}

HOOKS: dict[str, dict[str, Any]] = {
    name: {**DEFINITIONS[name], "fn": fn, "input": model_in, "output": model_out}
    for name, (fn, model_in, model_out) in _CODE.items()
}

_RUNNERS = {
    "before_save": runtime.before_save,
    "validate": runtime.validate,
    "after_save": runtime.after,
    "after_commit": runtime.after,
}
# Hooks that run in a repository stage. A validate hook runs in the before_save stage, after the
# before_save hooks (the chain has no separate validate stage for hooks yet).
_STAGE_OF = {"before_save": "before_save", "validate": "before_save", "after_save": "after_save", "after_commit": "after_commit"}
_ORDER = {"before_save": 0, "validate": 1, "after_save": 0, "after_commit": 0}


def merge_hooks(*sets: dict[str, tuple[Hook, ...]]) -> dict[str, tuple[Hook, ...]]:
    """One hooks table out of several blocks' tables: per stage, the hooks run in the order given."""
    merged: dict[str, tuple[Hook, ...]] = {}
    for hooks in sets:
        for stage, funcs in hooks.items():
            merged[stage] = (*merged.get(stage, ()), *funcs)
    return merged


def _bind(hook: dict[str, Any]) -> Hook:
    runner = _RUNNERS[hook["stage"]]

    async def run(ctx: HookContext) -> None:
        await runner(hook, ctx)

    return run


def hooks_for(entity: str) -> dict[str, tuple[Hook, ...]]:
    """The lifecycle hooks of one entity, by repository stage."""
    chosen = sorted(
        (h for h in HOOKS.values() if h["entity"] == entity and h["stage"] in _STAGE_OF),
        key=lambda h: (_ORDER[h["stage"]], h["name"]),
    )
    table: dict[str, list[Hook]] = {}
    for hook in chosen:
        table.setdefault(_STAGE_OF[hook["stage"]], []).append(_bind(hook))
    return {stage: tuple(funcs) for stage, funcs in table.items()}


async def check_guards(entity: str, transition: str, item: Any, caller: Any) -> None:
    """Run the guard hooks of one manual transition (by name); the first refusal wins."""
    guards = sorted(
        (
            h
            for h in HOOKS.values()
            if h["stage"] == "transition_guard" and h["entity"] == entity and h["transition"] == transition
        ),
        key=lambda h: h["name"],
    )
    for hook in guards:
        await runtime.check_guard(hook, item, caller)
