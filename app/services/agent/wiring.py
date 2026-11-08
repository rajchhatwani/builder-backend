"""Binds the run loop (run_service) to the real tools, approvals and gates.

The adapters are stateless; each call works on the session the run was loaded with.
"""

import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session

from app.config import get_settings
from app.core.spec_models import Spec, spec_hash
from app.exceptions import AppError
from app.models.agent import AiApproval, AiRun
from app.models.workspace import Workspace, WorkspaceCheckpoint
from app.services.agent import gates as gate_lib
from app.services.agent import promote as promote_lib
from app.services.agent import tools as tool_lib
from app.services.agent.approval_service import ApprovalService
from app.services.agent.contract import (
    ApprovalKind,
    ApprovalRequest,
    PermissionClass,
    Phase,
    RuleFailure,
    Tool,
    ToolContext,
    ToolResult,
)
from app.services.agent.draft import run_spec
from app.services.agent.run_service import AgentDeps
from app.services.ai.base import ToolDefinition
from app.services.dependency_policy_service import DependencyPolicyService


def _session(run: AiRun) -> AsyncSession:
    session = async_object_session(run)
    if session is None:  # a detached run must never be gated or approved
        raise AppError("agent_unavailable", "the run is not attached to a session", 500)
    return session


class Toolbox:
    def definitions(self, phase: Phase) -> list[ToolDefinition]:
        return tool_lib.tool_definitions(phase)

    def tool_set_hash(self, phase: Phase) -> str:
        return tool_lib.tool_set_hash(phase)

    async def execute(self, ctx: ToolContext, name: str, input: dict) -> ToolResult:  # type: ignore[type-arg]
        result = await tool_lib.execute(ctx, name, input)
        tool = tool_lib.REGISTRY.get(name)
        if (
            result.ok
            and tool is not None
            and tool.perm in (PermissionClass.S, PermissionClass.C)
            and ctx.workspace_id is not None
        ):
            # Spec edits flow into the draft's generated files; custom files are never rewritten.
            from app.services.workspace_service import WorkspaceService

            draft = await run_spec(ctx.session, ctx.run_id, ctx.project_id)
            await WorkspaceService(ctx.session).sync_generated(ctx.project_id, ctx.workspace_id, draft)
        return result

    def tools(self, phase: Phase) -> list[Tool]:
        return tool_lib.tools_for(phase)

    async def sync_draft(self, run: AiRun) -> None:
        """Regenerate the draft's generated files after the loop itself changed the draft spec (an
        approved D action); custom files are never rewritten."""
        if run.workspace_id is None:
            return
        from app.services.workspace_service import WorkspaceService

        session = _session(run)
        draft = await run_spec(session, run.id, run.project_id)
        await WorkspaceService(session).sync_generated(run.project_id, run.workspace_id, draft)


async def _workspace(run: AiRun) -> Workspace | None:
    if run.workspace_id is None:
        return None
    return await _session(run).get(Workspace, run.workspace_id)


def _content_hash_sync(root: Path) -> str:
    tree = gate_lib._scan_tree(root, time.monotonic() + gate_lib.MAX_SECONDS)
    digest = hashlib.sha256()
    for rel in sorted(tree.files):
        try:
            data = (root / rel).read_bytes()
        except OSError:
            data = b"\x00unreadable"
        digest.update(f"{rel}\0{hashlib.sha256(data).hexdigest()}\n".encode("utf-8", "surrogateescape"))
    if tree.hazard:  # a link or special file or a scan limit: never equal to a clean tree
        digest.update(b"hazard")
    return digest.hexdigest()


async def content_hash(path: str | None) -> str | None:
    """First 40 hex of sha256 over the sorted (path, sha256) of every non-.git file of the draft.
    Unlike git HEAD it moves with ANY edit, committed or not."""
    if not path or not Path(path).is_dir():
        return None
    return (await asyncio.to_thread(_content_hash_sync, Path(path)))[:40]


async def _git(path: str, *args: str) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", path, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    out, _ = await proc.communicate()
    return out.decode(errors="replace").splitlines() if proc.returncode == 0 else []


async def _changed_files(session: AsyncSession, ws: Workspace | None, cap: int = 100) -> list[str]:
    """Paths that differ from the draft's first checkpoint (committed or not, plus untracked)."""
    if ws is None or not ws.worktree_path or not Path(ws.worktree_path).is_dir():
        return []
    first = (
        await session.execute(
            select(WorkspaceCheckpoint.git_sha)
            .where(WorkspaceCheckpoint.workspace_id == ws.id)
            .order_by(WorkspaceCheckpoint.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    names: set[str] = set()
    if first:
        names.update(await _git(ws.worktree_path, "diff", "--name-only", first))
    names.update(await _git(ws.worktree_path, "ls-files", "-o", "--exclude-standard"))
    return sorted(n[:200] for n in names)[:cap]


class Approvals:
    """Binds each approval to the CURRENT spec hash and a hash of the draft's file CONTENT."""

    async def _bound(self, run: AiRun) -> tuple[str, str | None]:
        spec = await run_spec(_session(run), run.id, run.project_id)
        ws = await _workspace(run)
        return spec_hash(spec), await content_hash(ws.worktree_path if ws else None)

    async def request(self, run: AiRun, request: ApprovalRequest) -> uuid.UUID:
        digest, commit = await self._bound(run)
        before: Spec | None = None
        after: Spec | None = None
        if request.kind == ApprovalKind.C and request.payload.get("final") is True:
            request, before, after = await self._final(run, request)
        svc = await ApprovalService.for_project(_session(run), get_settings(), run.project_id)
        row = await svc.request(
            run, request, spec_hash=digest, commit=commit, spec_before=before, spec_after=after
        )
        return row.id

    async def validate_for_use(self, run: AiRun, approval: AiApproval, *, strict_payload: bool = False) -> None:
        """Raise AppError unless THIS approved row is unexpired, bound to the spec hash and content hash
        the run has NOW, and its payload still hashes to what was asked (S1-004)."""
        digest, commit = await self._bound(run)
        ApprovalService.check_usable(approval, spec_hash=digest, commit=commit, strict_payload=strict_payload)

    async def prepare_promotion(self, run: AiRun) -> dict[str, bytes]:
        """B-004, before apply: the custom-zone files the VALID final approval covers, re-read from the
        worktree and checked against the approved hashes. AppError when any differs. Files outside the
        approval are not in the result, so they are never promoted."""
        digest, commit = await self._bound(run)
        svc = await ApprovalService.for_project(_session(run), get_settings(), run.project_id)
        row = await svc.require_valid(run.id, ApprovalKind.C, spec_hash=digest, commit=commit)
        payload = row.payload or {}
        ws = await _workspace(run)
        if payload.get("final") is not True or ws is None or not ws.worktree_path:
            return {}
        return await asyncio.to_thread(promote_lib.collect, Path(ws.worktree_path), payload.get("file_hashes"))

    async def promote(self, run: AiRun, files: dict[str, bytes]) -> dict[str, Any]:
        """B-004, after apply: commit the verified files to the project's live code (idempotent)."""
        if not files:
            return {"promoted": [], "commit": None}
        from app.services.workspace_service import WorkspaceService

        ws = await _workspace(run)
        sha = await WorkspaceService(_session(run)).promote_files(
            run.project_id, files, f"agent run {run.id}: custom code approved in the final review",
            base_branch=ws.branch if ws is not None else None,
        )
        return {"promoted": sorted(files), "commit": sha}

    async def _final(
        self, run: AiRun, request: ApprovalRequest
    ) -> tuple[ApprovalRequest, Spec | None, Spec]:
        """The final review lists what changed: AI/changed hooks (with author, so the owner rule
        applies), files, and the risk flags of the run's DRAFT against the spec the plan was approved on."""
        session = _session(run)
        now = await run_spec(session, run.id, run.project_id)
        raw = (run.plan or {}).get("base_spec") if isinstance(run.plan, dict) else None
        base = Spec.model_validate(raw) if isinstance(raw, dict) else None
        base_hooks = {h.name: h.model_dump(mode="json") for h in base.hooks} if base else {}
        hooks = [
            {"name": h.name, "author": getattr(h, "author", None) or "human"}
            for h in now.hooks
            if getattr(h, "author", None) == "ai" or base_hooks.get(h.name) != h.model_dump(mode="json")
        ]
        payload = dict(request.payload)
        if hooks:
            payload["hooks"] = hooks[:100]
        ws = await _workspace(run)
        payload["files"] = await _changed_files(session, ws)
        if ws is not None and ws.worktree_path and Path(ws.worktree_path).is_dir():
            # B-004: the custom-zone files this approval covers, with their hashes (bound by the payload hash)
            payload["file_hashes"] = await asyncio.to_thread(
                promote_lib.custom_file_hashes, Path(ws.worktree_path), payload["files"]
            )
        payload["spec_diff"] = spec_changes(base, now)
        payload["empty_change"] = not payload["spec_diff"] and not payload["files"]  # nothing to apply
        payload["gates_green"] = True  # a finish is only accepted when G0-G9 are green
        return ApprovalRequest(request.kind, request.subject, payload), base, now

    async def require_valid(self, run: AiRun, kind: ApprovalKind) -> None:
        digest, commit = await self._bound(run)
        await ApprovalService(_session(run), get_settings()).require_valid(
            run.id, kind, spec_hash=digest, commit=commit
        )


def spec_changes(before: Spec | None, after: Spec) -> list[dict[str, Any]]:
    """What the draft changed against the spec the plan was approved on: per top-level section,
    named items added / removed / changed, or just 'changed' for sections without named items."""
    b = before.model_dump(mode="json") if before is not None else {}
    a = after.model_dump(mode="json")
    out: list[dict[str, Any]] = []
    for sec in sorted(set(a) | set(b)):
        x, y = b.get(sec), a.get(sec)
        if x == y:
            continue
        if isinstance(x or [], list) and isinstance(y or [], list) and all(
            isinstance(i, dict) and "name" in i for i in [*(x or []), *(y or [])]
        ):
            xm = {i["name"]: i for i in x or []}
            ym = {i["name"]: i for i in y or []}
            out.append(
                {
                    "section": sec,
                    "added": sorted(set(ym) - set(xm))[:50],
                    "removed": sorted(set(xm) - set(ym))[:50],
                    "changed": sorted(n for n in set(xm) & set(ym) if xm[n] != ym[n])[:50],
                }
            )
        else:
            out.append({"section": sec, "changed": True})
    return out


class Gates:
    async def worktree(self, run: AiRun) -> str | None:
        ws = await _workspace(run)
        return ws.worktree_path if ws else None

    async def check(self, run: AiRun) -> list[RuleFailure]:
        return (await self.check_report(run))[0]

    async def check_report(self, run: AiRun) -> tuple[list[RuleFailure], str]:
        path = await self.worktree(run)
        if not path or not Path(path).is_dir():
            return [
                RuleFailure(
                    "gates.no_workspace", "run", "a draft workspace to check", "none attached",
                    "create a workspace and start the run with workspace_id",
                )
            ], ""
        session = _session(run)
        spec = await run_spec(session, run.id, run.project_id)
        pins = [
            (r.package, r.version, r.hashes)
            for r in await DependencyPolicyService(session).approved_pins(run.project_id)
        ]
        root = Path(path)
        first = await asyncio.to_thread(gate_lib.run_gates, root, spec, approved_pins=pins)
        second = await asyncio.to_thread(gate_lib.replay, root, spec, pins)
        failures = [*first.failures, *second.failures]
        report = gate_lib.GateReport(ok=not failures, failures=failures, gates=first.gates)
        return failures, gate_lib.report_hash(report)


def default_deps() -> AgentDeps:
    return AgentDeps(toolbox=Toolbox(), approvals=Approvals(), gates=Gates())
