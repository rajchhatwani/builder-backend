"""Effects of effectful hooks (generated). TRUSTED AUTHORS ONLY: hooks run in the API process without a
sandbox until Cycle 3, so only trusted developers of this project may write them.

A hook sends things out ONLY through these functions: no sockets, no HTTP client, no subprocess (the gate
refuses those imports). Every call is charged against the hook's declared `effects` and `effect_budget`
(see budget.py) before anything leaves; breaking a limit aborts the hook and its failure policy applies.
Secrets never reach the hook: credentials are read by the provider framework inside the platform, and
only a small result (accepted / status code / number queued) comes back. Logs carry the hook, the
effect and the outcome, never the payload. Reads still go through `find_rows`, which follows the
access rules of the person whose request runs the hook."""

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from app.db import session_factory
from app.notifications import service as notification_service
from app.platform_sdk import budget
from app.platform_sdk.env import BudgetExceeded, HookEnv, _env, log
from app.providers import client as provider_client
from app.providers.schemas import EmailRequest, SmsRequest

NIL_TENANT = uuid.UUID(int=0)
LIMITS: dict[str, budget.EffectLimits] = {
    "announce_order": budget.EffectLimits(
        effects=frozenset(['email', 'notification']),
        wall_seconds=1.1,
        calls_per_effect=2,
        payload_bytes=2000,
        outbound_per_minute=10,
    ),
}
WEBHOOK_HOSTS: frozenset[str] = frozenset([])


class EffectFailed(Exception):
    """The outside call failed. Only a short code is kept: never the text of the error."""


def _charge(effect: str, size: int) -> HookEnv:
    env = _env()
    if env.breached:  # once any budget is broken, EVERY further effect of this invocation is refused
        log.warning("hook_effect_refused", hook=env.hook, effect=effect, reason="breached")
        raise BudgetExceeded("breached")
    try:
        budget.LEDGER.charge(env.hook, LIMITS.get(env.hook), env.effect_calls, effect, size, env.t0)
    except budget.OverBudget as over:
        env.breached = True
        log.warning("hook_effect_refused", hook=env.hook, effect=effect, reason=over.code)
        raise BudgetExceeded(over.code) from None
    return env


def _run(env: HookEnv, effect: str, work: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Run the platform coroutine on the app loop, bounded by what is left of the hook's wall clock."""
    limits = LIMITS[env.hook]
    left = max(0.05, limits.wall_seconds - (time.monotonic() - env.t0))
    future = asyncio.run_coroutine_threadsafe(work(), env.loop)
    try:
        result = future.result(timeout=left)
    except TimeoutError:
        future.cancel()
        env.breached = True
        raise BudgetExceeded("wall_clock") from None
    except Exception as exc:
        log.warning("hook_effect_failed", hook=env.hook, effect=effect, error=type(exc).__name__)
        raise EffectFailed(type(exc).__name__) from None
    log.info("hook_effect", hook=env.hook, effect=effect, outcome="ok")
    return result


def _tenant(env: HookEnv) -> uuid.UUID:
    return getattr(env.caller, "tenant_id", None) or NIL_TENANT


def _size(*parts: str) -> int:
    return sum(len(p.encode("utf-8")) for p in parts)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email through the tenant's email provider (the emulator in tests). True when accepted."""
    env = _charge("email", _size(to, subject, body))

    async def work() -> bool:
        async with session_factory() as session:
            result = await provider_client.call_provider(
                session, _tenant(env), "email", EmailRequest(to=to, subject=subject, body=body)
            )
        return bool(getattr(result, "accepted", True))

    return bool(_run(env, "email", work))


def send_sms(to: str, body: str) -> bool:
    """Send a text message through the tenant's SMS provider. True when accepted."""
    env = _charge("sms", _size(to, body))

    async def work() -> bool:
        async with session_factory() as session:
            result = await provider_client.call_provider(session, _tenant(env), "sms", SmsRequest(to=to, body=body))
        return bool(getattr(result, "accepted", True))

    return bool(_run(env, "sms", work))


def notify(
    type_name: str, recipient_key: str, variables: dict[str, Any], email: str | None = None, phone: str | None = None
) -> int:
    """Queue a declared notification type (templates, preferences and the delivery log apply). Returns
    the number of delivery-log rows created."""
    env = _charge("notification", _size(type_name, recipient_key, json.dumps(variables, default=str)))

    async def work() -> int:
        recipient = notification_service.Recipient(key=recipient_key, email=email, phone=phone)
        async with session_factory() as session:
            created = await notification_service.notify(
                session, type_name, recipient, variables, tenant_id=_tenant(env)
            )
            await session.commit()
        return len(created)

    return int(_run(env, "notification", work))
