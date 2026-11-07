"""Helpers shared by the agent tools: result builders, the untrusted-data wrapper, safe paths."""

import json
from pathlib import Path, PurePosixPath
from typing import Any

from app.core import hook_gates
from app.core.generator.zones import zone_for
from app.exceptions import AppError
from app.services.agent.contract import RuleFailure, ToolContext, ToolResult

OUTPUT_CAP = 20_000  # characters of JSON a tool may hand back to the model
INPUT_CAP = 100_000  # characters of JSON a call may carry
READ_CAP = 16_000  # bytes read_file returns
WRITE_CAP = 40_000  # bytes a code tool writes

DENIED_SEGMENTS = frozenset(
    {".git", ".ssh", ".aws", ".gnupg", "secrets", "secret", ".secrets", "terraform", ".terraform",
     ".github", ".gitlab", ".circleci", ".venv", "venv", "node_modules"}
)  # fmt: skip
DENIED_NAMES = frozenset({"id_rsa", "id_ed25519", ".netrc", ".npmrc", ".pypirc", "credentials", ".gitlab-ci.yml"})
DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".tf", ".tfstate", ".tfvars")


class ToolRefusal(Exception):
    """Raised inside a handler to refuse with a RuleFailure; `execute` turns it into a result."""

    def __init__(self, failure: RuleFailure) -> None:
        super().__init__(failure.rule_id)
        self.failure = failure


def failure(rule_id: str, location: str, expected: str, actual: str, hint: str = "") -> RuleFailure:
    return RuleFailure(rule_id, location, expected, actual[:300], hint)


def fail(rule_id: str, location: str, expected: str, actual: str, hint: str = "") -> ToolResult:
    return ToolResult(ok=False, failures=(failure(rule_id, location, expected, actual, hint),))


def refuse(rule_id: str, location: str, expected: str, actual: str, hint: str = "") -> ToolRefusal:
    return ToolRefusal(failure(rule_id, location, expected, actual, hint))


def _detail_text(exc: AppError) -> str:
    """The validation issues behind a 422, so the agent can see WHAT to repair (first real run: it
    only saw '1 new validation issue' and gave up). Short, project-own spec text only."""
    out: list[str] = []
    for d in (exc.details or [])[:3]:
        if isinstance(d, dict):
            loc = d.get("path") or d.get("location") or d.get("section") or ""
            msg = d.get("message") or d.get("detail") or d.get("code") or ""
            out.append(f"{loc}: {msg}".strip(": ")[:200])
    return "; ".join(x for x in out if x)


def app_error_failure(tool: str, exc: AppError) -> RuleFailure:
    detail = _detail_text(exc)
    return failure(
        exc.code or "tool_error",
        tool,
        "the operation is valid for the current spec",
        f"{exc.message}: {detail}" if detail else exc.message,
        "fix the input and call the tool again" if exc.status_code < 500 else "",
    )


def untrusted(text: Any) -> Any:
    """Project text is data. The envelope tells the model (and the tests) it is never an instruction."""
    return {"untrusted_text": text if isinstance(text, str) else str(text)}


def dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)


SECURITY_SUBSTRINGS = ("role", "permission", "access", "tenan", "public", "auth")
SECURITY_EXEMPT = frozenset({"author"})  # the hook author mark is ours, not an access setting


def has_key(obj: Any, parts: tuple[str, ...] = SECURITY_SUBSTRINGS) -> str | None:
    """First dict key (any depth) whose lower-cased name contains one of `parts`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            low = str(k).lower()
            if low not in SECURITY_EXEMPT and any(p in low for p in parts):
                return str(k)
            found = has_key(v, parts)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = has_key(v, parts)
            if found:
                return found
    return None


# -- paths -------------------------------------------------------------------------------


def _clean_rel(rel: str, tool: str) -> PurePosixPath:
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel or len(rel) > 300:
        raise refuse("path_invalid", tool, "a relative posix path", "empty or malformed path")
    p = PurePosixPath(rel)
    if p.is_absolute() or any(part in ("", ".", "..") for part in rel.split("/")):
        raise refuse("path_invalid", tool, "a relative path inside the worktree", "absolute path or '..'")
    return p


def _denied(p: PurePosixPath) -> bool:
    for part in p.parts:
        low = part.lower()
        if (
            low in DENIED_SEGMENTS
            or low in DENIED_NAMES
            or low.startswith(".env")
            or low.endswith(DENIED_SUFFIXES)
        ):
            return True
    return False


def worktree_root(ctx: ToolContext, tool: str) -> Path:
    if not ctx.worktree:
        raise refuse("no_worktree", tool, "a draft worktree", "this run has no worktree")
    root = Path(ctx.worktree)
    if not root.is_dir():
        raise refuse("no_worktree", tool, "a draft worktree", "the worktree folder is missing")
    return root.resolve()


def safe_path(ctx: ToolContext, rel: str, tool: str, *, must_exist: bool) -> tuple[Path, str]:
    """(absolute path, normalised relative path). No traversal, no symlink anywhere on the way,
    nothing under .git / .env / secrets folders."""
    root = worktree_root(ctx, tool)
    p = _clean_rel(rel, tool)
    if _denied(p):
        raise refuse("path_denied", rel, "a project file", "git data, env files and secrets are not readable")
    cur = root
    for part in p.parts:
        cur = cur / part
        if cur.is_symlink():
            raise refuse("path_symlink", rel, "a regular file", "a symbolic link is on the path")
    target = root / Path(*p.parts)
    if root not in target.resolve().parents:
        raise refuse("path_outside", rel, "a path inside the worktree", "resolves outside it")
    if must_exist and not target.is_file():
        raise refuse("path_missing", rel, "an existing file", "no such file")
    return target, p.as_posix()


def custom_write_path(ctx: ToolContext, rel: str, tool: str) -> tuple[Path, str]:
    """A path the agent may write: custom zone only, never a guarded, generated, gate, CI or IaC file."""
    target, norm = safe_path(ctx, rel, tool, must_exist=False)
    if (
        zone_for(norm) != "custom"
        or hook_gates.is_guarded_path(norm)
        or norm.startswith("platform/")
        or norm.endswith((".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".sh"))
        or "platform_gate" in norm
    ):
        raise refuse(
            "zone_denied",
            norm,
            "a file in the custom zone (app/custom/, app/hooks/, tests/custom/)",
            "generated, guarded, gate, CI or infrastructure path",
            "write only your hook bodies and tests",
        )
    return target, norm
