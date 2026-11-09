"""FX-5 / A-011: the X tools that run code, ONLY inside the existing sandbox / preview runtime.

  run_tests      pytest over the draft's tests/custom in a throwaway gVisor sandbox (read-only code,
                 no egress, wall-clock and memory limits). Caches are cleaned first (G8 refuses them).
  start_preview  starts (or reuses) the preview of the run's draft workspace through PreviewService, so
                 every preview quota, kill switch and limit applies. The preview token is never shown.
  call_endpoint  one request to that running preview, through the same address check the proxy uses.

Nothing here runs in the API process, opens a socket outside the preview network address, or gives the
model a credential. Output is redacted, capped and handed back as untrusted data.
"""

import asyncio
from typing import Any

import httpx
from sqlalchemy import select

from app.exceptions import AppError
from app.services.agent.cache_clean import clean_caches
from app.services.agent.contract import ToolContext, ToolResult
from app.services.agent.tools._common import fail, failure, untrusted, worktree_root

TEST_DIR = "tests/custom"
TEST_COMMAND = ["python", "-m", "pytest", TEST_DIR, "-q", "-x", "--no-header", "-p", "no:cacheprovider"]
OUTPUT_TAIL = 4_000
CALL_BODY_CAP = 8_000
CALL_RESPONSE_CAP = 6_000


def _tail(text: str) -> str:
    from app.services import preview_runtime

    return preview_runtime.redact(text)[-OUTPUT_TAIL:]


async def run_tests(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    from app.services import preview_service
    from app.services.sandbox import SandboxError
    from app.services.sandbox.base import Limits, SandboxSpec

    root = worktree_root(ctx, "run_tests")
    await asyncio.to_thread(clean_caches, root)
    if not (root / TEST_DIR).is_dir():
        return ToolResult(ok=True, data={"status": "no_tests", "note": f"the draft has no {TEST_DIR} folder yet"})
    box = preview_service.get_sandbox(ctx.settings)
    spec = SandboxSpec(
        image=ctx.settings.preview_app_image,
        command=TEST_COMMAND,
        code_dir=root,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "APP_ENV": "test"},
        limits=Limits(cpus=1.0, memory="512m", pids=100, wall_seconds=90, ttl_seconds=300),
    )
    try:
        res = await box.run(spec)
    except (SandboxError, OSError, TimeoutError) as exc:
        return fail("sandbox_unavailable", "run_tests", "a sandbox that runs the tests", type(exc).__name__,
                    "the sandbox runtime is not available; use run_gates")  # fmt: skip
    finally:
        await asyncio.to_thread(clean_caches, root)
    passed = res.exit_code == 0 and not res.timed_out and not res.oom_killed
    data = {
        "status": "passed" if passed else "timed_out" if res.timed_out else "failed",
        "exit_code": res.exit_code,
        "oom_killed": res.oom_killed,
        "duration_seconds": round(res.duration_seconds, 2),
        "output": untrusted(_tail(res.stdout + ("\n" + res.stderr if res.stderr else ""))),
    }
    if passed:
        return ToolResult(ok=True, data=data)

    return ToolResult(ok=False, data=data, failures=(failure(
        "tests.failed", TEST_DIR, "all custom tests pass", f"status {data['status']}, exit {res.exit_code}",
        "read the output, fix the hook body or the test, and run again"),))  # fmt: skip


async def _live_preview(ctx: ToolContext) -> Any:
    from app.models.preview import LIVE_STATES, Preview

    if ctx.session is None or ctx.workspace_id is None:
        return None
    return (
        await ctx.session.execute(
            select(Preview)
            .where(Preview.project_id == ctx.project_id, Preview.workspace_id == ctx.workspace_id,
                   Preview.state.in_(LIVE_STATES))
            .order_by(Preview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def start_preview(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    from app.models.platform import PlatformUser
    from app.services import preview_service as ps

    if ctx.workspace_id is None:
        return fail("no_worktree", "start_preview", "a draft workspace", "this run has no workspace")
    row = await _live_preview(ctx)
    created = False
    if row is None:
        user = await ctx.session.get(PlatformUser, ctx.actor.user_id) if ctx.actor.user_id else None
        if user is None:
            return fail("no_actor", "start_preview", "the user who started the run", "unknown user")
        try:
            made = await ps.PreviewService(ctx.session, ctx.settings).create(ctx.project_id, user, ctx.workspace_id)
        except AppError as exc:  # quotas, kill switch, capacity: the platform's answer, unchanged
            return fail(exc.code or "preview_refused", "start_preview", "a preview within the platform limits",
                        exc.message, "do not retry; ask the user to free a preview")  # fmt: skip
        pid, created = made.id, True
    else:
        pid = row.id
    try:
        p = await ps.ensure_running(pid, float(ctx.settings.preview_wake_timeout_seconds))
    except AppError as exc:
        return fail(exc.code or "preview_failed", "start_preview", "a running preview", exc.message)
    return ToolResult(ok=True, data={"status": "running", "preview_id": str(p.id), "created": created})


async def call_endpoint(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    from app.api.previews import verify_upstream
    from app.services import preview_runtime as rt
    from app.services import preview_service as ps

    path = str(args["path"])
    if not path.startswith("/") or "//" in path[:2] or any(ord(c) < 33 or ord(c) == 127 for c in path) or "#" in path:
        return fail("path_invalid", "call_endpoint", "a path starting with / without spaces", path[:80])
    row = await _live_preview(ctx)
    if row is None:
        return fail("no_preview", "call_endpoint", "a running preview of this draft", "none is running",
                    "call start_preview first")  # fmt: skip
    try:
        p = await ps.ensure_running(row.id, float(ctx.settings.preview_wake_timeout_seconds))
        await verify_upstream(ps.get_sandbox(ctx.settings), p)
        await ps.touch(p.id)
    except AppError as exc:
        return fail(exc.code or "preview_failed", "call_endpoint", "a reachable preview", exc.message)
    body = args.get("json")
    url = f"http://{p.app_ip}:{rt.APP_PORT}{path}"
    try:
        async with httpx.AsyncClient(timeout=float(ctx.settings.preview_request_timeout_seconds), trust_env=False,
                                     follow_redirects=False) as client:
            resp = await client.request(args["method"], url, json=body if body is not None else None)
    except httpx.HTTPError as exc:
        return fail("preview_unreachable", "call_endpoint", "an answer from the preview", type(exc).__name__)
    text = rt.redact(resp.text[: CALL_RESPONSE_CAP + 1])
    return ToolResult(ok=True, data={
        "status_code": resp.status_code,
        "content_type": resp.headers.get("content-type", "")[:80],
        "truncated": len(text) > CALL_RESPONSE_CAP,
        "body": untrusted(text[:CALL_RESPONSE_CAP]),
    })  # fmt: skip
