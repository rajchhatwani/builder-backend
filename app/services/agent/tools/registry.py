"""The one tool registry and the ONLY execution path (`execute`)."""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.exceptions import AppError
from app.services.agent.contract import (
    PHASE_CLASSES,
    PermissionClass,
    Phase,
    RuleFailure,
    Tool,
    ToolContext,
    ToolResult,
)
from app.services.ai.base import ToolDefinition, prefix_digest

from . import approval_tools, code_tools, read_tools, sandbox_tools, spec_tools
from ._common import INPUT_CAP, OUTPUT_CAP, ToolRefusal, app_error_failure, dumps, failure
from ._schema import validate

Scope = Callable[[ToolContext, dict[str, Any]], Awaitable[tuple[str, str] | None]]

_MODULES = (read_tools, spec_tools, code_tools, sandbox_tools, approval_tools)
REGISTRY: dict[str, Tool] = {}
SCOPES: dict[str, Scope] = {}
for _m in _MODULES:
    for _t in _m.TOOLS:
        assert _t.name not in REGISTRY, _t.name
        REGISTRY[_t.name] = _t
    SCOPES.update(_m.SCOPES)
assert len(REGISTRY) < 30
WRITE_CLASSES = frozenset({PermissionClass.S, PermissionClass.S_BANG, PermissionClass.C, PermissionClass.C_BANG})


def tools_for(phase: Phase) -> list[Tool]:
    allowed = PHASE_CLASSES[phase]
    return sorted((t for t in REGISTRY.values() if t.perm in allowed), key=lambda t: t.name)


def tool_definitions(phase: Phase) -> list[ToolDefinition]:
    return [ToolDefinition(t.name, t.description, t.input_schema) for t in tools_for(phase)]


def tool_set_hash(phase: Phase) -> str:
    return prefix_digest("", tool_definitions(phase))


def _fail(rule: str, location: str, expected: str, actual: str, hint: str = "") -> ToolResult:
    return ToolResult(ok=False, failures=(failure(rule, location, expected, actual, hint),))


def cap_result(result: ToolResult) -> ToolResult:
    """Output over the cap is cut: data becomes a truncated text preview, failures are limited."""
    failures = result.failures[:50]
    data = result.data
    text = dumps(data)
    if len(text) > OUTPUT_CAP:
        data = {"truncated": True, "original_chars": len(text), "preview": text[:OUTPUT_CAP]}
    if data is result.data and failures == result.failures:
        return result
    return ToolResult(result.ok, data, failures, result.approval, result.needs_plan_extension)


async def execute(ctx: ToolContext, name: str, input: dict[str, Any]) -> ToolResult:  # noqa: A002
    try:
        return cap_result(await _execute(ctx, name, input))
    except ToolRefusal as exc:
        return cap_result(ToolResult(ok=False, failures=(exc.failure,)))
    except AppError as exc:
        return cap_result(ToolResult(ok=False, failures=(app_error_failure(str(name)[:60], exc),)))
    except Exception as exc:  # a tool must never take the loop down; type only, no message
        return _fail("tool_error", str(name)[:60], "the tool completes", type(exc).__name__)


async def _execute(ctx: ToolContext, name: str, input: dict[str, Any]) -> ToolResult:  # noqa: A002
    tool = REGISTRY.get(name) if isinstance(name, str) else None
    if tool is None:
        return _fail("tool_unknown", str(name)[:60], "a listed tool", "unknown tool", "use only the tools you were given")
    if tool.perm not in PHASE_CLASSES[ctx.phase]:
        return _fail("tool_phase", name, f"a tool of phase {ctx.phase.value}", f"class {tool.perm.value}",
                     "this tool is not available in the current phase")  # fmt: skip
    if not isinstance(input, dict):
        return _fail("tool_input", name, "a JSON object", type(input).__name__)
    try:
        size = len(json.dumps(input, default=str))
    except (TypeError, ValueError):
        return _fail("tool_input", name, "JSON input", "not serialisable")
    if size > INPUT_CAP:
        return _fail("tool_input", name, f"at most {INPUT_CAP} characters", f"{size} characters")
    errors = validate(input, tool.input_schema)
    if errors:
        fails = tuple(
            RuleFailure("tool_input", f"{name}:{loc}", "input matching the tool schema", msg, "")
            for loc, msg in errors[:5]
        )
        return ToolResult(ok=False, failures=fails)
    if ctx.plan is None:
        if ctx.phase is not Phase.plan:
            return _fail("plan_required", name, "an approved plan", "this run has no plan",
                         "a plan must be approved before build or apply tools run")  # fmt: skip
    else:
        if tool.perm in WRITE_CLASSES and not (ctx.plan.entities or ctx.plan.hooks or ctx.plan.zones
                                               or ctx.plan.dependencies):
            return ToolResult(ok=False, needs_plan_extension=("plan", "empty"), failures=(failure(
                "plan_scope", name, "a plan that lists what may change", "the plan is empty",
                "nothing may change under an empty plan"),))  # fmt: skip
        scope = SCOPES.get(name)
        if scope is not None:
            outside = await scope(ctx, input)
            if outside is not None:
                return ToolResult(ok=False, needs_plan_extension=outside, failures=(failure(
                    "plan_scope", name, "a target listed in the approved plan", f"{outside[0]} {outside[1][:80]}",
                    "ask for a plan extension; do not retry"),))  # fmt: skip
    return await tool.handler(ctx, input)
