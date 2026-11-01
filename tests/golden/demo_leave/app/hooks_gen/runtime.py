"""Runs custom hooks under their contract (generated).

A call builds the typed input model, runs the hook function in a worker thread with a wall-clock
limit (its cpu_ms budget plus a small allowance), checks that the result is the output model and
applies the failure policy:

  fail_closed  the operation is refused (guards and validation hooks are always fail_closed)
  fail_open    the failure is logged and the operation goes on as if the hook had not run
  fallback     the declared fallback values stand in for the hook's output

A failure never carries the hook's own message (it may contain data): only the hook name, the point
and a short reason are logged.

What the time limit does and does not do: when a hook is still running at the deadline the CALLER gives
up (HookFailed "timeout", the failure policy applies). The worker thread is NOT stopped; Python cannot
stop a thread, and a C-level loop (a regex, a huge integer power) holds the GIL for its whole run. What
bounds the damage today is (1) the gate, which statically refuses the known ways to run for ever or to
allocate without limit (the `re` module, unbounded iterators, recursion, huge powers/ranges/repeats),
and (2) a small dedicated executor, so stuck hooks can occupy at most MAX_HOOK_THREADS threads and can
never exhaust the loop's default executor that the rest of the API uses. Real isolation (a subprocess
with CPU and memory rlimits, killed on timeout) is the Cycle 3 sandbox and is not built yet.
"""

import asyncio
import datetime as _dt
import decimal
import importlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import sqlalchemy as sa
import structlog
from pydantic import BaseModel

from app.core.errors import AppError
from app.crud.lifecycle import HookContext
from app.db import session_factory
from app.platform_sdk import env as sdk_env

logger = structlog.get_logger()

GRACE_SECONDS = 0.1
MAX_HOOK_THREADS = 4
# Hooks never run on the loop's default executor: a stuck hook must not starve the rest of the API.
_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_HOOK_THREADS, thread_name_prefix="hook")
MAX_TEXT = 200
_PLAIN = (str, int, float, bool, type(None), decimal.Decimal, _dt.date, _dt.datetime, uuid.UUID)


class HookFailed(Exception):
    """A hook broke its contract or its budget."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _text(value: object) -> str:
    return str(value)[:MAX_TEXT] if value is not None else ""


def _payload(hook: dict[str, Any], values: dict[str, Any] | None, item: Any) -> dict[str, Any]:
    """Input values by field name: pending values first (before_save), else the record."""
    out: dict[str, Any] = {}
    for name in hook["input_fields"]:
        if values is not None and name in values:
            out[name] = values[name]
        elif item is not None:
            out[name] = getattr(item, name, None)
        else:
            out[name] = None
    return out


async def _find(
    ref: tuple[str, str], equals: dict[str, Any], limit: int, caller: Any
) -> list[dict[str, Any]]:
    model = getattr(importlib.import_module(ref[0]), ref[1])
    columns = {attr.key for attr in sa.inspect(model).column_attrs}
    if not set(equals) <= columns:
        raise ValueError("unknown column in the filter")
    stmt = sa.select(model).limit(limit)
    for key, value in equals.items():
        stmt = stmt.where(getattr(model, key) == value)
    if "deleted_at" in columns:
        stmt = stmt.where(model.deleted_at.is_(None))
    if "tenant_id" in columns:
        tenant_id = getattr(caller, "tenant_id", None)
        if tenant_id is None:
            return []  # no tenant, no rows
        stmt = stmt.where(model.tenant_id == tenant_id)
    async with session_factory() as session:
        await session.execute(sa.text("SET TRANSACTION READ ONLY"))
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {key: getattr(row, key) for key in sorted(columns) if isinstance(getattr(row, key), _PLAIN)}
        for row in rows
    ]


def _finder(
    hook: dict[str, Any], caller: Any, loop: asyncio.AbstractEventLoop, deadline: float
) -> sdk_env.Finder | None:
    if not hook["reads"]:
        return None
    models = hook["models"]

    def find(entity: str, equals: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        left = max(0.05, deadline - time.monotonic())
        future = asyncio.run_coroutine_threadsafe(_find(models[entity], equals, limit, caller), loop)
        return future.result(timeout=left)

    return find


async def call(hook: dict[str, Any], payload: dict[str, Any], caller: Any) -> BaseModel:
    """Run one hook. Raises HookFailed on any breach; never returns something that is not the
    declared output model."""
    try:
        data = hook["input"](**payload)
    except Exception as exc:
        raise HookFailed("input_invalid") from exc
    loop = asyncio.get_running_loop()
    timeout = hook["cpu_ms"] / 1000 + GRACE_SECONDS
    env = sdk_env.HookEnv(
        hook=hook["name"],
        caller=caller,
        loop=loop,
        rows_budget=hook["rows"],
        reads=frozenset(hook["reads"]),
        finder=_finder(hook, caller, loop, time.monotonic() + timeout),
    )
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_EXECUTOR, sdk_env.call_in_env, env, hook["fn"], data), timeout
        )
    except TimeoutError as exc:
        raise HookFailed("timeout") from exc
    except Exception as exc:
        raise HookFailed(type(exc).__name__) from exc
    if env.breached:
        raise HookFailed("budget")
    if not isinstance(result, hook["output"]):
        raise HookFailed("bad_output")
    return result  # type: ignore[no-any-return]


async def _guarded(
    hook: dict[str, Any], payload: dict[str, Any], caller: Any
) -> BaseModel | None:
    """`call` plus the failure policy: the output, or None when the operation goes on without it."""
    try:
        return await call(hook, payload, caller)
    except HookFailed as failure:
        logger.error("hook_failed", hook=hook["name"], point=hook["point"], reason=failure.reason)
        if hook["policy"] == "fallback":
            output: BaseModel = hook["output"](**hook["fallback"])
            return output
        if hook["policy"] == "fail_open":
            return None
        raise AppError("hook_failed", f"the {hook['name']} hook failed", 500) from failure


def _setting(hook: dict[str, Any], name: str, value: Any) -> Any:
    allowed = hook["enums"].get(name)
    if allowed is not None and value not in allowed:
        raise AppError("hook_failed", f"the {hook['name']} hook returned a value that is not allowed", 500)
    return value


async def before_save(hook: dict[str, Any], ctx: HookContext) -> None:
    if ctx.op == "delete":
        return
    out = await _guarded(hook, _payload(hook, ctx.values, ctx.item), ctx.caller)
    if out is None:
        return
    for name in hook["output_fields"]:
        value = getattr(out, name)
        if value is not None:
            ctx.values[name] = _setting(hook, name, value)


async def validate(hook: dict[str, Any], ctx: HookContext) -> None:
    if ctx.op == "delete":
        return
    out = await _guarded(hook, _payload(hook, ctx.values, ctx.item), ctx.caller)
    if out is not None and getattr(out, "valid", None) is not True:
        message = _text(getattr(out, "message", None)) or f"the {hook['name']} check failed"
        raise AppError("hook_validation_failed", message, 422)


async def after(hook: dict[str, Any], ctx: HookContext) -> None:
    """after_save / after_commit: the output is checked and then dropped."""
    if ctx.op == "delete" or ctx.item is None:
        return
    await _guarded(hook, _payload(hook, None, ctx.item), ctx.caller)


async def check_guard(hook: dict[str, Any], item: Any, caller: Any) -> None:
    out = await _guarded(hook, _payload(hook, None, item), caller)
    if out is not None and getattr(out, "allowed", None) is not True:
        reason = _text(getattr(out, "reason", None))
        suffix = f": {reason}" if reason else ""
        raise AppError(
            "transition_refused",
            f"the conditions for {hook['transition']} are not met{suffix}",
            409,
        )
