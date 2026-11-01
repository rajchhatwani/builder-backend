"""What a running hook can reach (generated): the caller, a read-only row finder and the log.

A hook body imports from `app.platform_sdk` only. This module is the other half of that facade:
the runtime binds an environment for the duration of one call, the SDK functions read it.
"""

import asyncio
import contextvars
import dataclasses
import datetime as _dt
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
import structlog

from app.auth import config as auth_config
from app.auth.identity import Principal
from app.auth.models import AuthIdentity, AuthTenant
from app.auth.service import effective_roles
from app.db import session_factory

log = structlog.get_logger("hook")

Finder = Callable[[str, dict[str, Any], int], list[dict[str, Any]]]
_SCALARS = (str, int, float, bool)


class BudgetExceeded(Exception):
    """The hook read more rows than its budget, or touched something it was not granted."""


@dataclasses.dataclass
class HookEnv:
    hook: str
    caller: Any
    loop: asyncio.AbstractEventLoop
    rows_budget: int
    reads: frozenset[str]
    finder: Finder | None
    rows_used: int = 0
    breached: bool = False
    principal_loaded: bool = False
    principal_value: Any = None


_ENV: contextvars.ContextVar[HookEnv | None] = contextvars.ContextVar("hook_env", default=None)


def call_in_env(env: HookEnv, fn: Callable[[Any], Any], arg: Any) -> Any:
    """Run `fn(arg)` (in a worker thread) with `env` bound for that call only."""
    ctx = contextvars.copy_context()
    ctx.run(_ENV.set, env)
    return ctx.run(fn, arg)


def _env() -> HookEnv:
    env = _ENV.get()
    if env is None:
        raise RuntimeError("this SDK function works only inside a running hook")
    return env


def now() -> _dt.datetime:
    """The current time (UTC). Effect hooks only: a pure hook must get times from its input."""
    return _dt.datetime.now(_dt.UTC)


def find_rows(entity: str, *, limit: int = 50, **equals: Any) -> list[dict[str, Any]]:
    """Read-only lookup: rows of `entity` whose columns equal the given values, as plain dicts.

    Only the entities the hook declares in `reads` can be read, only up to its `rows` budget, and
    only inside the caller's tenant. Nothing can be written through this function."""
    env = _env()
    if env.finder is None or entity not in env.reads:
        env.breached = True
        raise BudgetExceeded("this hook may not read that entity")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if any(not isinstance(v, _SCALARS) for v in equals.values()):
        raise ValueError("filter values must be plain strings, numbers or booleans")
    remaining = env.rows_budget - env.rows_used
    if remaining <= 0 or limit > remaining:
        env.breached = True
        raise BudgetExceeded("the rows budget of this hook is used up")
    rows = env.finder(entity, equals, limit)
    env.rows_used += len(rows)
    return rows


async def _load_principal(caller: Any) -> Principal | None:
    if caller is None:
        return None
    async with session_factory() as session:
        found = (
            await session.execute(
                sa.select(AuthIdentity)
                .where(AuthIdentity.user_id == caller.id)
                .order_by(AuthIdentity.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        tenant_id = getattr(caller, "tenant_id", None)
        tenant = await session.get(AuthTenant, tenant_id) if tenant_id is not None else None
    return Principal(
        user_id=caller.id,
        issuer=found.issuer if found is not None else auth_config.ISSUER,
        subject=found.subject if found is not None else "",
        tenant_id=tenant_id,
        tenant_external_ref=tenant.external_ref if tenant is not None else None,
        roles=tuple(sorted(effective_roles(caller.roles))),
        session_id=None,
        auth_time=None,
    )


def current_principal() -> Principal | None:
    """The signed-in caller as a `Principal` (None for a system write). Never read token claims."""
    env = _env()
    if not env.principal_loaded:
        future = asyncio.run_coroutine_threadsafe(_load_principal(env.caller), env.loop)
        env.principal_value = future.result(timeout=2.0)
        env.principal_loaded = True
    return env.principal_value  # type: ignore[no-any-return]
