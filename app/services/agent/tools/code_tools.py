"""Class C: code in the draft worktree's custom zone only. Every write runs the hook gates before it
is kept; a failing write is rolled back to the previous bytes and the findings come back as
RuleFailures. Nothing here can write a generated, guarded, gate, CI or infrastructure file."""

import ast
import asyncio
import hashlib
import json
import textwrap
from pathlib import Path, PurePosixPath
from typing import Any

from app.core import hook_gates
from app.core.generator.engine import generate
from app.core.spec_models import Spec
from app.exceptions import AppError
from app.services.agent import gates as agent_gates
from app.services.agent.contract import (
    ApprovalKind,
    ApprovalRequest,
    PermissionClass,
    RuleFailure,
    Tool,
    ToolContext,
    ToolResult,
)
from app.services.agent.draft import add_draft_op, run_spec

from ._common import (
    WRITE_CAP,
    _clean_rel,
    app_error_failure,
    custom_write_path,
    fail,
    failure,
    refuse,
    worktree_root,
)

REFRESH_PREFIXES = ("app/hooks_gen/",)
REFRESH_FILES = ("platform/hooks.json", "platform/zones.json")
_GATE_HINT = {
    "G0": "keep the stub frame (signature line and body markers) exactly as generated",
    "G1": "use only allowed imports (stdlib subset, pydantic, app.platform_sdk)",
    "G2": "remove the banned name or call",
    "G3": "do not read identity, headers, tokens or secret-looking literals",
    "G4": "keep the hook pure: no I/O, clock, randomness or global writes",
    "G5": "return the declared output model",
    "G6": "reduce size, loops or recursion",
    "G7": "only the body of a declared hook may change",
}


def gate_failures(findings: list[hook_gates.Finding]) -> tuple[RuleFailure, ...]:
    return tuple(
        RuleFailure(f.rule, f"{f.file}:{f.line}", f"gate {f.gate} passes", f.message, _GATE_HINT.get(f.gate, ""))
        for f in findings[:50]
    )


async def load_spec(ctx: ToolContext) -> Spec:
    return await run_spec(ctx.session, ctx.run_id, ctx.project_id)


async def mark_hook_author(ctx: ToolContext, name: str) -> None:
    """Record author 'ai' on the hook in the spec (the spec's value for agent-written code)."""
    spec = await load_spec(ctx)
    items = [h.model_dump(mode="json") for h in spec.hooks]
    for item in items:
        if item["name"] == name:
            if item.get("author") == "ai":
                return
            item["author"] = "ai"
    await add_draft_op(ctx.session, ctx.run_id, ctx.project_id, "set_section", {"section": "hooks", "items": items})


def _manifest_entry(root: Path, name: str) -> dict[str, Any] | None:
    path = root / hook_gates.MANIFEST_PATH
    if path.is_symlink():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for raw in manifest.get("hooks", []):
        if raw.get("name") == name:
            return dict(raw)
    return None


def _restore(target: Path, old: bytes | None) -> None:
    if old is None:
        target.unlink(missing_ok=True)
    else:
        target.write_bytes(old)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _review(ctx: ToolContext, name: str, rel: str, data: bytes, what: str) -> ApprovalRequest:
    return ApprovalRequest(
        ApprovalKind.C,
        f"{what} hook {name}: owner review of agent-written code",
        {"hook": name, "file": rel, "sha256": _digest(data), "author": "ai", "run_id": str(ctx.run_id)},
    )


def _trusted_write(root: Path, rel: str, content: str) -> None:
    cur = root
    for part in PurePosixPath(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            raise refuse("path_symlink", rel, "a regular file", "a symbolic link is on the path")
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


async def create_custom_hook(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    name = args["name"]
    root = worktree_root(ctx, "create_custom_hook")
    spec = await load_spec(ctx)
    if not any(h.name == name for h in spec.hooks):
        return fail("hook_not_declared", name, "a hook declared in the spec",
                    "no such hook", "declare it first with set_section(section=hooks, items=[...])")  # fmt: skip
    try:
        files = await asyncio.to_thread(generate, spec)
    except Exception as exc:  # InvalidSpecError and friends: the spec must be valid to render a stub
        return fail("spec_invalid", name, "a valid spec", type(exc).__name__, "fix the spec first")
    stub_rel = f"{hook_gates.HOOK_DIR}/{name}.py"
    if stub_rel not in files:
        return fail("hook_no_stub", name, "a stub for this hook", "the generator renders none")
    target, norm = custom_write_path(ctx, stub_rel, "create_custom_hook")
    if target.exists():
        owed = None
        if ctx.reexecution and any(h.name == name and h.author == "ai" for h in spec.hooks):
            # S1-008: this very call already wrote the stub before a crash; the owner review it owes must
            # not be lost with the first attempt.
            owed = _review(ctx, name, norm, target.read_bytes(), "created")
        return ToolResult(ok=True, data={"hook": name, "file": norm, "created": False,
                                         "note": "the stub exists; use replace_function_body"},
                          approval=owed)  # fmt: skip
    for rel, content in sorted(files.items()):
        if rel in REFRESH_FILES or rel.startswith(REFRESH_PREFIXES):
            _trusted_write(root, rel, content)
    _trusted_write(root, norm, files[stub_rel])
    findings, _ = hook_gates.check_files(root, [str(target)])
    findings = [f for f in findings if f.rule != "G5.not_implemented"]  # a fresh stub is unimplemented by design
    if findings:
        _restore(target, None)
        return ToolResult(ok=False, failures=gate_failures(findings))
    try:
        await mark_hook_author(ctx, name)
    except AppError as exc:
        _restore(target, None)
        return ToolResult(ok=False, failures=(app_error_failure("create_custom_hook", exc),))
    data = target.read_bytes()
    return ToolResult(ok=True, data={"hook": name, "file": norm, "created": True, "author": "ai",
                                     "purpose": args["purpose"][:300]},
                      approval=_review(ctx, name, norm, data, "created"))  # fmt: skip


async def replace_function_body(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    name, body = args["hook"], args["body"]
    root = worktree_root(ctx, "replace_function_body")
    entry = _manifest_entry(root, name)
    if entry is None:
        return fail("hook_not_declared", name, "a hook in platform/hooks.json", "not found",
                    "declare the hook and call create_custom_hook first")  # fmt: skip
    target, norm = custom_write_path(ctx, str(entry["file"]), "replace_function_body")
    if not target.is_file():
        return fail("hook_no_stub", norm, "the stub file", "missing", "call create_custom_hook")
    old = target.read_bytes()
    lines = hook_gates.split_lines(old.decode("utf-8", errors="replace"))
    found = hook_gates.body_range(lines, name)
    if found is None:
        return fail("G0.frame", norm, "intact body markers", "markers missing or duplicated")
    start, end = found
    new_body = [("    " + ln) if ln.strip() else "" for ln in textwrap.dedent(body).split("\n")]
    while new_body and not new_body[-1]:
        new_body.pop()
    text = "\n".join([*lines[: start + 1], *new_body, *lines[end:]])
    target.write_bytes(text.encode("utf-8"))
    findings, _ = hook_gates.check_files(root, [str(target)])
    if findings:
        _restore(target, old)
        return ToolResult(ok=False, failures=gate_failures(findings))
    try:
        await mark_hook_author(ctx, name)
    except AppError as exc:
        _restore(target, old)
        return ToolResult(ok=False, failures=(app_error_failure("replace_function_body", exc),))
    return ToolResult(ok=True, data={"hook": name, "file": norm, "author": "ai", "lines": len(new_body)},
                      approval=_review(ctx, name, norm, target.read_bytes(), "changed"))  # fmt: skip


def _test_findings(root: Path, norm: str, content: str) -> tuple[RuleFailure, ...]:
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return (failure("G1.syntax", f"{norm}:{exc.lineno or 1}", "valid python", "syntax error"),)
    banned = hook_gates.BANNED_MODULES | hook_gates.NETWORK_MODULES
    out: list[RuleFailure] = []
    for f in agent_gates.check_banned(norm, tree):  # importlib, builtins, __builtins__, from os import system ...
        out.append(RuleFailure(f.rule_id, f.location, f.expected, f.actual, _GATE_HINT["G1"]))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("open", "getattr"):
            first = node.args[0] if node.args else None
            text = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
            if node.func.id == "open" and (text is None or text.startswith("/") or ".." in text):
                out.append(failure("G2.open_path", f"{norm}:{getattr(node, 'lineno', 1)}", "open() of a literal relative path",
                                   "absolute, parent or computed path", "tests read no files outside the project"))
            if node.func.id == "getattr" and not (len(node.args) > 1 and isinstance(node.args[1], ast.Constant)):
                out.append(failure("G2.dynamic_getattr", f"{norm}:{getattr(node, 'lineno', 1)}", "getattr with a literal name",
                                   "computed attribute name", ""))
    for node in ast.walk(tree):
        mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
            [node.module or ""] if isinstance(node, ast.ImportFrom) else [])  # fmt: skip
        for m in mods:
            if m.split(".")[0] in banned:
                out.append(failure("G1.import_banned", f"{norm}:{getattr(node, 'lineno', 1)}", "an allowed import",
                                   f"import of {m.split('.')[0]}", _GATE_HINT["G1"]))
    if out:
        return tuple(out)
    findings, _ = hook_gates.check_project(root)
    return gate_failures([f for f in findings if f.file == norm])


async def add_test(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    content = args["content"]
    root = worktree_root(ctx, "add_test")
    target, norm = custom_write_path(ctx, args["path"], "add_test")
    if not norm.startswith("tests/custom/") or not norm.endswith(".py"):
        return fail("zone_denied", norm, "tests/custom/<name>.py", norm, "tests live in tests/custom/")
    if len(content.encode()) > WRITE_CAP:
        return fail("tool_input", norm, f"at most {WRITE_CAP} bytes", "content too large")
    old = target.read_bytes() if target.is_file() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
    failures = await asyncio.to_thread(_test_findings, root, norm, content)
    if failures:
        _restore(target, old)
        return ToolResult(ok=False, failures=failures)
    return ToolResult(ok=True, data={"file": norm, "sha256": _digest(target.read_bytes()), "replaced": old is not None})


async def _scope_hook(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    assert ctx.plan is not None
    name = str(args.get("name") or args.get("hook"))
    return None if name in ctx.plan.hooks else ("hook", name)


async def _scope_test(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, str] | None:
    assert ctx.plan is not None
    rel = _clean_rel(args["path"], "add_test").as_posix()
    if ctx.plan.allows("zone", rel):
        return None
    stem = PurePosixPath(rel).name.removesuffix(".py").removeprefix("test_")
    if any(stem == h or stem.startswith(h + "_") for h in ctx.plan.hooks):
        return None
    return ("zone", rel)


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


C = PermissionClass.C
TOOLS: list[Tool] = [
    Tool("create_custom_hook",
         "Render the stub of a hook that is declared in the spec (and in the plan). Needs owner review.",
         _obj({"name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,62}$"},
               "purpose": {"type": "string", "minLength": 1, "maxLength": 500}}, ["name", "purpose"]),
         C, create_custom_hook),
    Tool("replace_function_body",
         "Replace the body of a hook between its markers. Gates run on every write; a failing write is undone.",
         _obj({"hook": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,62}$"},
               "body": {"type": "string", "minLength": 1, "maxLength": WRITE_CAP}}, ["hook", "body"]),
         C, replace_function_body),
    Tool("add_test", "Add or replace a test file under tests/custom/.",
         _obj({"path": {"type": "string", "minLength": 1, "maxLength": 200},
               "content": {"type": "string", "minLength": 1, "maxLength": WRITE_CAP}}, ["path", "content"]),
         C, add_test),
]  # fmt: skip
SCOPES: dict[str, Any] = {
    "create_custom_hook": _scope_hook,
    "replace_function_body": _scope_hook,
    "add_test": _scope_test,
}
