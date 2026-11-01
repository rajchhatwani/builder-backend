"""Scenario tests for the generated `hooks_invoice` project. Copied into the project's tests/ folder by
tests/e2e/test_hooks_stack.py (after the gate has passed on the hook bodies) and run on a real Postgres.

Rules under test: the guard hook decides a manual transition (allow, deny with a reason); under
fail_closed an exception, a timeout, a wrong return type or an input that breaks the contract refuses the
transition and leaves the state unchanged; the effect hook runs after commit and under fail_open its
failures never reach the caller; budgets are enforced; the hook sees only the typed input model.
"""

import importlib
import time
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.hooks_gen import contracts, registry, runtime
from app.main import app

sdk = importlib.import_module("app.platform_sdk")


class Recorder:
    """Stands in for a structlog logger: remembers (event, fields)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def info(self, event: str, **fields) -> None:  # noqa: ANN003
        self.events.append((event, fields))

    error = warning = info


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "clerk": await sign_in(http, "clerk@example.com", roles=["clerk"], n=0),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=1),
    }


@pytest.fixture
def effect_log(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(sdk, "log", recorder)
    return recorder


@pytest.fixture
def runtime_log(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(runtime, "logger", recorder)
    return recorder


async def make(http: AsyncClient, who: dict[str, str], number: str = "INV-1", amount: str = "1000.00", po: str = "1000.00") -> str:
    response = await http.post(
        "/invoices", json={"invoice_no": number, "amount": amount, "po_amount": po}, headers=who
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def submit(http: AsyncClient, who: dict[str, str], invoice: str):  # noqa: ANN201
    return await http.post(f"/invoices/{invoice}/transitions/submit", headers=who)


async def status(http: AsyncClient, who: dict[str, str], invoice: str) -> str:
    return (await http.get(f"/invoices/{invoice}", headers=who)).json()["status"]


async def history(http: AsyncClient, who: dict[str, str], invoice: str) -> list[str]:
    rows = (await http.get(f"/invoices/{invoice}/state-history", headers=who)).json()
    return [row["transition"] for row in rows]


def patch_guard(monkeypatch: pytest.MonkeyPatch, fn) -> None:  # noqa: ANN001
    monkeypatch.setitem(registry.HOOKS["match_invoice"], "fn", fn)


# --- the guard ---------------------------------------------------------------------------------


async def test_the_guard_body_allows_a_transition(http, people) -> None:  # noqa: ANN001
    invoice = await make(http, people["clerk"])
    moved = await submit(http, people["clerk"], invoice)
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "approved"  # submit, then the automatic approval


async def test_the_guard_body_can_refuse_with_a_reason(http, people) -> None:  # noqa: ANN001
    refused_number = await make(http, people["clerk"], number="DENY")
    refused = await submit(http, people["clerk"], refused_number)
    assert refused.status_code == 409 and refused.json()["code"] == "transition_refused"
    assert "variance too high" in refused.json()["message"]
    assert await status(http, people["clerk"], refused_number) == "draft"
    assert await history(http, people["clerk"], refused_number) == ["created"]
    far = await make(http, people["clerk"], amount="1000.00", po="100.00")
    assert (await submit(http, people["clerk"], far)).status_code == 409
    assert await status(http, people["clerk"], far) == "draft"


async def test_the_body_itself_raising_refuses_the_transition(http, people) -> None:  # noqa: ANN001
    invoice = await make(http, people["clerk"], number="RAISE")
    response = await submit(http, people["clerk"], invoice)
    assert response.status_code == 500 and response.json()["code"] == "hook_failed"
    assert "boom" not in response.text  # the hook's own message is never shown
    assert await status(http, people["clerk"], invoice) == "draft"


async def test_an_exception_refuses_and_leaves_the_state(http, people, monkeypatch, runtime_log) -> None:  # noqa: ANN001
    def explode(data):  # noqa: ANN001, ANN202
        raise RuntimeError("secret detail 123")

    patch_guard(monkeypatch, explode)
    invoice = await make(http, people["clerk"])
    response = await submit(http, people["clerk"], invoice)
    assert response.status_code == 500 and response.json()["code"] == "hook_failed"
    assert "secret detail" not in response.text
    assert await status(http, people["clerk"], invoice) == "draft"
    assert await history(http, people["clerk"], invoice) == ["created"]
    event, fields = runtime_log.events[-1]
    assert event == "hook_failed" and fields["hook"] == "match_invoice" and fields["reason"] == "RuntimeError"
    assert "secret detail" not in str(fields)
    monkeypatch.undo()  # the failure left nothing locked: the same record can be moved afterwards
    assert (await submit(http, people["clerk"], invoice)).status_code == 200


async def test_a_timeout_refuses_and_leaves_the_state(http, people, monkeypatch, runtime_log) -> None:  # noqa: ANN001
    def slow(data):  # noqa: ANN001, ANN202
        total = 0
        for _ in range(30_000):
            for _ in range(1_000):
                total += 1
        return contracts.MatchResult(allowed=True)

    patch_guard(monkeypatch, slow)
    invoice = await make(http, people["clerk"])
    started = time.monotonic()
    response = await submit(http, people["clerk"], invoice)
    assert response.status_code == 500 and response.json()["code"] == "hook_failed"
    assert time.monotonic() - started < 3.0
    assert runtime_log.events[-1][1]["reason"] == "timeout"
    assert await status(http, people["clerk"], invoice) == "draft"


async def test_a_wrong_return_type_refuses(http, people, monkeypatch, runtime_log) -> None:  # noqa: ANN001
    patch_guard(monkeypatch, lambda data: data)  # returns the input model, not the output model
    invoice = await make(http, people["clerk"])
    response = await submit(http, people["clerk"], invoice)
    assert response.status_code == 500
    assert runtime_log.events[-1][1]["reason"] == "bad_output"
    assert await status(http, people["clerk"], invoice) == "draft"
    patch_guard(monkeypatch, lambda data: {"allowed": True})  # a dict is not the model either
    assert (await submit(http, people["clerk"], invoice)).status_code == 500


async def test_the_guard_gets_only_the_typed_input(http, people, monkeypatch) -> None:  # noqa: ANN001
    seen = []

    def spy(data):  # noqa: ANN001, ANN202
        seen.append(data)
        return contracts.MatchResult(allowed=True)

    patch_guard(monkeypatch, spy)
    invoice = await make(http, people["clerk"], number="INV-77", amount="12.50", po="12.00")
    assert (await submit(http, people["clerk"], invoice)).status_code == 200
    assert len(seen) == 1 and type(seen[0]) is contracts.MatchInput
    assert seen[0].model_dump() == {"invoice_no": "INV-77", "amount": Decimal("12.50"), "po_amount": Decimal("12.00")}
    with pytest.raises(Exception):  # noqa: B017, PT011 (frozen model)
        seen[0].amount = Decimal(1)


async def test_the_role_check_still_comes_first(http, people, monkeypatch) -> None:  # noqa: ANN001
    calls = []
    patch_guard(monkeypatch, lambda data: calls.append(1) or contracts.MatchResult(allowed=True))
    invoice = await make(http, people["clerk"])
    other = await sign_in(http, "nobody@example.com", roles=["approver"], n=5)
    assert (await submit(http, other, invoice)).status_code in (403, 404)
    assert calls == []  # the guard hook never ran for a caller who may not make the move


async def test_a_second_move_is_not_blocked_by_a_failed_one(http, people, monkeypatch) -> None:  # noqa: ANN001
    patch_guard(monkeypatch, lambda data: (_ for _ in ()).throw(RuntimeError("x")))
    invoice = await make(http, people["clerk"])
    for _ in range(3):
        assert (await submit(http, people["clerk"], invoice)).status_code == 500
    monkeypatch.undo()
    assert (await submit(http, people["clerk"], invoice)).status_code == 200


# --- the effect (after_commit, fail_open) ------------------------------------------------------


async def test_the_effect_runs_after_the_write_and_reads_rows(http, people, effect_log) -> None:  # noqa: ANN001
    first = await make(http, people["clerk"], number="INV-9")
    await make(http, people["clerk"], number="INV-9")
    notified = [fields for event, fields in effect_log.events if event == "notified"]
    assert [n["same"] for n in notified] == [1, 2]  # it saw the committed rows, itself included
    assert notified[0]["status"] == "draft" and notified[0]["at"].endswith("+00:00")
    await submit(http, people["clerk"], first)
    last = [fields for event, fields in effect_log.events if event == "notified"][-1]
    assert last["status"] == "approved"  # also after a transition


async def test_fail_open_an_effect_that_raises_never_fails_the_request(http, people, effect_log, runtime_log) -> None:  # noqa: ANN001
    response = await http.post(
        "/invoices",
        json={"invoice_no": "EFFECT-FAIL", "amount": "10.00", "po_amount": "10.00"},
        headers=people["clerk"],
    )
    assert response.status_code == 201, response.text
    assert (await http.get(f"/invoices/{response.json()['id']}", headers=people["clerk"])).status_code == 200
    assert [e for e, _ in effect_log.events if e == "notified"] == []
    assert runtime_log.events[-1][0] == "hook_failed" and runtime_log.events[-1][1]["hook"] == "notify_approved"


async def test_effect_timeout_and_wrong_output_are_swallowed_too(http, people, monkeypatch, runtime_log) -> None:  # noqa: ANN001
    def slow(data):  # noqa: ANN001, ANN202
        total = 0
        for _ in range(40_000):
            for _ in range(1_000):
                total += 1
        return contracts.NotifyResult(sent=True)

    monkeypatch.setitem(registry.HOOKS["notify_approved"], "fn", slow)
    await make(http, people["clerk"], number="INV-1")
    assert runtime_log.events[-1][1]["reason"] == "timeout"
    monkeypatch.setitem(registry.HOOKS["notify_approved"], "fn", lambda data: 42)
    await make(http, people["clerk"], number="INV-2")
    assert runtime_log.events[-1][1]["reason"] == "bad_output"


async def test_the_rows_budget_is_enforced(http, people, monkeypatch, runtime_log) -> None:  # noqa: ANN001
    def greedy(data):  # noqa: ANN001, ANN202
        sdk.find_rows("Invoice", limit=21)  # the budget is 20 rows
        return contracts.NotifyResult(sent=True)

    monkeypatch.setitem(registry.HOOKS["notify_approved"], "fn", greedy)
    await make(http, people["clerk"])
    assert runtime_log.events[-1][1]["reason"] == "BudgetExceeded"

    def swallowing(data):  # noqa: ANN001, ANN202
        try:
            sdk.find_rows("Invoice", limit=21)
        except Exception:  # noqa: BLE001
            pass
        return contracts.NotifyResult(sent=True)

    monkeypatch.setitem(registry.HOOKS["notify_approved"], "fn", swallowing)
    await make(http, people["clerk"], number="INV-2")
    assert runtime_log.events[-1][1]["reason"] == "budget"  # a breach cannot be hidden by catching it


async def test_a_hook_cannot_read_what_it_was_not_granted(http, people, monkeypatch, runtime_log) -> None:  # noqa: ANN001
    def nosy(data):  # noqa: ANN001, ANN202
        sdk.find_rows("AuthUser")
        return contracts.NotifyResult(sent=True)

    monkeypatch.setitem(registry.HOOKS["notify_approved"], "fn", nosy)
    await make(http, people["clerk"])
    assert runtime_log.events[-1][1]["reason"] == "BudgetExceeded"

    def bad_filter(data):  # noqa: ANN001, ANN202
        sdk.find_rows("Invoice", nonexistent_column=1)
        return contracts.NotifyResult(sent=True)

    monkeypatch.setitem(registry.HOOKS["notify_approved"], "fn", bad_filter)
    await make(http, people["clerk"], number="INV-3")
    assert runtime_log.events[-1][0] == "hook_failed"


async def test_the_sdk_works_only_inside_a_hook() -> None:
    with pytest.raises(RuntimeError):
        sdk.find_rows("Invoice")
    with pytest.raises(RuntimeError):
        sdk.current_principal()


async def test_the_principal_comes_from_the_sdk_not_from_claims(http, people, monkeypatch) -> None:  # noqa: ANN001
    seen = []

    def who(data):  # noqa: ANN001, ANN202
        principal = sdk.current_principal()
        seen.append(principal)
        return contracts.MatchResult(allowed=True)

    patch_guard(monkeypatch, who)
    invoice = await make(http, people["clerk"])
    await submit(http, people["clerk"], invoice)
    assert seen and seen[0] is not None
    assert "clerk" in seen[0].roles and isinstance(seen[0].user_id, uuid.UUID)
    assert seen[0].issuer and seen[0].subject
