"""Runs INSIDE a generated hooks_effects project (copied to tests/test_effects_runtime.py by test_hooks_effects_stack.py).

Real Postgres, the provider EMULATOR (APP_ENV=test), no network. One asyncio.run so the engine keeps one loop.
Proves: effects work inside the budget; every budget (calls per effect, payload, undeclared effect, per minute,
wall clock) aborts the hook; the declared failure policy decides what the caller sees; the abort carries no data."""

import asyncio
import time
import uuid
from typing import Any

import pytest

from app import db
from app.core.errors import AppError
from app.hooks_gen import contracts, registry, runtime
from app.platform_sdk import budget, notify, send_email, send_sms

BASE = registry.HOOKS["announce_order"]


def hook(fn: Any, **changes: Any) -> dict[str, Any]:
    return {**BASE, "fn": fn, **changes}


def payload(reference: str = "R-1") -> dict[str, Any]:
    return {"id": uuid.uuid4(), "reference": reference}


def ok_result(data: Any) -> Any:
    return contracts.AnnounceResult(sent=True)


def one_mail(data: Any) -> Any:
    return contracts.AnnounceResult(sent=send_email("buyer@example.com", "hello", "body"))


def three_mails(data: Any) -> Any:
    for _ in range(3):
        send_email("buyer@example.com", "hello", "body")
    return ok_result(data)


def big_mail(data: Any) -> Any:
    send_email("buyer@example.com", "hello", "x" * 5000)
    return ok_result(data)


def undeclared_sms(data: Any) -> Any:
    send_sms("+10000000000", "hi")
    return ok_result(data)


def slow_then_mail(data: Any) -> Any:
    time.sleep(1.4)
    send_email("buyer@example.com", "late", "body")
    return ok_result(data)


def swallow(data: Any) -> Any:
    try:
        three_mails(data)
    except Exception:  # noqa: BLE001 - a hook that hides the breach must still be aborted
        pass
    return ok_result(data)


def breach_then_mail(data: Any) -> Any:
    try:
        big_mail(data)
    except Exception:  # noqa: BLE001 - swallowed on purpose
        pass
    send_email("buyer@example.com", "hello", "body")  # within every limit, but the invocation already broke one
    return ok_result(data)


def queue_notification(data: Any) -> Any:
    n = notify("welcome", str(data.id), {"name": "Ann"}, email="ann@example.com")
    return contracts.AnnounceResult(sent=n == 1)


async def failure(fn: Any, **changes: Any) -> str:
    with pytest.raises(runtime.HookFailed) as info:
        await runtime.call(hook(fn, **changes), payload(), None)
    return info.value.reason


async def scenarios() -> None:
    db.engine.sync_engine.dispose(close=False)  # drop connections another test loop may have left in the pool
    # inside the budget: an email through the emulator, and a queued notification (delivery-log row)
    assert (await runtime.call(hook(one_mail), payload(), None)).sent is True
    assert (await runtime.call(hook(queue_notification), payload(), None)).sent is True

    # budgets abort the hook
    assert await failure(three_mails) == "BudgetExceeded"  # calls per effect type: 2 allowed
    assert await failure(big_mail) == "BudgetExceeded"  # payload bytes: 2000 allowed
    assert await failure(undeclared_sms) == "BudgetExceeded"  # sms is not declared
    assert await failure(swallow) == "budget"  # catching the exception does not help
    assert await failure(slow_then_mail) == "timeout"  # wall clock

    # once a budget is broken, NO further effect of that invocation is sent, even a small declared one
    before = sum(len(w) for w in budget.LEDGER._sent.values())
    assert await failure(breach_then_mail) == "BudgetExceeded"  # the second send is refused ("breached"), not sent
    assert sum(len(w) for w in budget.LEDGER._sent.values()) == before

    # outbound per minute (10): this process already made some calls; keep going until the ledger refuses
    refused = None
    for _ in range(12):
        try:
            await runtime.call(hook(one_mail), payload(), None)
        except runtime.HookFailed as failed:
            refused = failed.reason
            break
    assert refused == "BudgetExceeded"
    budget.LEDGER._sent.clear()  # a minute later

    # the declared failure policy decides what the write sees (after_commit can never fail the write)
    fallback = await runtime._guarded(hook(three_mails, policy="fallback", fallback={"sent": False}), payload(), None)
    assert fallback is not None and fallback.sent is False
    assert await runtime._guarded(hook(three_mails, policy="fail_open"), payload(), None) is None
    with pytest.raises(AppError):
        await runtime._guarded(hook(three_mails, policy="fail_closed"), payload(), None)

    # the abort says what broke, never the data
    reason = await failure(big_mail)
    assert "xxxx" not in reason and "buyer" not in reason


def test_effect_budgets_and_failure_policy() -> None:
    asyncio.run(scenarios())
