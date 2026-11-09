"""Class X: work that runs inside the sandbox, never in the API process. `run_gates` calls the
injectable `run_gates_hook` (the gates agent replaces it); the rest are registered but report
`not_available` until a safe sandbox call exists for them."""

import asyncio
import time
from pathlib import Path
from typing import Any

from app.core import hook_gates
from app.services.agent.contract import PermissionClass, RuleFailure, Tool, ToolContext, ToolResult
from app.services.agent.draft import run_spec
from app.services.agent.gates import _scan_tree

from ._common import fail, worktree_root
from . import exec_tools
from .code_tools import gate_failures


async def run_gates_hook(ctx: ToolContext) -> list[RuleFailure]:
    """Default: the existing hook gates (pure `ast` checks, nothing is imported or run) over the worktree."""
    root = worktree_root(ctx, "run_gates")
    # L7: same guard as gates._hook_gates; a symlink or special file means nothing may follow paths
    tree = await asyncio.to_thread(_scan_tree, Path(root), time.monotonic() + 20.0)
    if tree.hazard:
        return [*tree.failures]
    # Same rule as gates._hook_gates: a project without hooks has no manifest and nothing for G0-G7
    # to check (found in the first real run: the tool failed every hook-less draft with G7.manifest).
    if ctx.session is not None and not (Path(root) / hook_gates.MANIFEST_PATH).exists():
        spec = await run_spec(ctx.session, ctx.run_id, ctx.project_id)
        if not spec.hooks:
            return []
    findings, _checked = await asyncio.to_thread(hook_gates.check_project, Path(root))
    return list(gate_failures(findings))


async def run_gates(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    failures = await run_gates_hook(ctx)
    return ToolResult(ok=not failures, data={"gates": "passed" if not failures else "failed"}, failures=tuple(failures))


def _not_available(tool: str, hint: str) -> Any:
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return fail("not_available", tool, "a sandbox runner", "not wired into the agent yet", hint)

    return handler


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


X = PermissionClass.X
TOOLS: list[Tool] = [
    Tool("run_gates", "Run the platform gates over the draft worktree.", _obj({}, []), X, run_gates),
    Tool("run_tests", "Run the custom tests of the draft (tests/custom) inside the sandbox. Caches are cleaned first.",
         _obj({}, []), X, exec_tools.run_tests),
    Tool("start_preview", "Start (or reuse) a sandboxed preview of the draft. Platform preview limits apply.",
         _obj({}, []), X, exec_tools.start_preview),
    Tool("call_endpoint", "Call an endpoint of the running preview of the draft (start_preview first).",
         _obj({"method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
               "path": {"type": "string", "maxLength": 300},
               "json": {"type": "object"}}, ["method", "path"]), X, exec_tools.call_endpoint),
]  # fmt: skip
SCOPES: dict[str, Any] = {}
