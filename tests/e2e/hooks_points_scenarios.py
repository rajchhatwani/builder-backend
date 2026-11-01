"""Scenario tests for the generated `hooks-points` project (hooks at every point of the lifecycle chain).
Copied into the project's tests/ folder by tests/e2e/test_hooks_stack.py and run on a real Postgres.

Rules under test: before_save hooks change the values that are written (in name order); a validate hook
runs after them and refuses with 422; an after_save hook that fails under fail_closed rolls the write back;
the fallback policy substitutes the declared output; hooks do not run on delete.
"""

import importlib
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.hooks_gen import registry, runtime
from app.main import app

sdk = importlib.import_module("app.platform_sdk")


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


def body(number: str = "inv-1", amount: str = "100.00", po: str = "100.00") -> dict[str, str]:
    return {"invoice_no": number, "amount": amount, "po_amount": po}


def spy(monkeypatch: pytest.MonkeyPatch, name: str, calls: list[str]) -> None:
    original = registry.HOOKS[name]["fn"]

    def wrapper(data):  # noqa: ANN001, ANN202
        calls.append(name)
        return original(data)

    monkeypatch.setitem(registry.HOOKS[name], "fn", wrapper)


async def test_before_save_changes_what_is_written(http, people) -> None:  # noqa: ANN001
    created = await http.post("/invoices", json=body("  inv-9 "), headers=people["clerk"])
    assert created.status_code == 201, created.text
    assert created.json()["invoice_no"] == "inv-9"
    url = f"/invoices/{created.json()['id']}"
    updated = await http.patch(url, json={"invoice_no": "  abc  "}, headers=people["admin"])
    assert updated.status_code == 200, updated.text
    assert updated.json()["invoice_no"] == "abc"  # an update runs the hook on the changed value
    untouched = await http.patch(url, json={"amount": "5.00"}, headers=people["admin"])
    assert untouched.json()["invoice_no"] == "abc"  # the stored value is read for a partial update


async def test_the_hooks_run_in_the_chain_order(http, people, monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []
    for name in ("default_po", "normalize_no", "check_amounts", "audit_save", "notify_approved"):
        spy(monkeypatch, name, calls)
    created = await http.post("/invoices", json=body(), headers=people["clerk"])
    assert created.status_code == 201, created.text
    # before_save hooks by name, then validate, then after_save, then (after the commit) the effect
    assert calls == ["default_po", "normalize_no", "check_amounts", "audit_save", "notify_approved"]


async def test_validate_sees_the_values_before_save_produced(http, people, monkeypatch) -> None:  # noqa: ANN001
    seen = []
    original = registry.HOOKS["check_amounts"]["fn"]

    def watch(data):  # noqa: ANN001, ANN202
        seen.append(data)
        return original(data)

    monkeypatch.setitem(registry.HOOKS["check_amounts"], "fn", watch)
    await http.post("/invoices", json=body("  lower "), headers=people["clerk"])
    assert seen[0].invoice_no == "lower"


async def test_a_validate_hook_refuses_with_422(http, people) -> None:  # noqa: ANN001
    refused = await http.post("/invoices", json=body(amount="2000000.00", po="2000000.00"), headers=people["clerk"])
    assert refused.status_code == 422 and refused.json()["code"] == "hook_validation_failed"
    assert refused.json()["message"] == "amount is too large"
    listing = await http.get("/invoices", headers=people["clerk"])
    assert listing.json()["total"] == 0
    created = await http.post("/invoices", json=body(), headers=people["clerk"])
    refused_update = await http.patch(
        f"/invoices/{created.json()['id']}", json={"amount": "2000000.00"}, headers=people["admin"]
    )
    assert refused_update.status_code == 422
    stored = (await http.get(f"/invoices/{created.json()['id']}", headers=people["admin"])).json()
    assert Decimal(stored["amount"]) == Decimal("100.00")


async def test_an_after_save_failure_rolls_the_write_back(http, people) -> None:  # noqa: ANN001
    failed = await http.post("/invoices", json=body("FAIL-AFTER-SAVE"), headers=people["clerk"])
    assert failed.status_code == 500 and failed.json()["code"] == "hook_failed"
    assert (await http.get("/invoices", headers=people["clerk"])).json()["total"] == 0


async def test_the_fallback_policy_substitutes_the_declared_output(http, people, monkeypatch) -> None:  # noqa: ANN001
    def explode(data):  # noqa: ANN001, ANN202
        raise RuntimeError("x")

    monkeypatch.setitem(registry.HOOKS["default_po"], "fn", explode)
    created = await http.post("/invoices", json=body(po="55.00"), headers=people["clerk"])
    assert created.status_code == 201, created.text
    assert Decimal(created.json()["po_amount"]) == Decimal("1.00")  # the declared fallback replaced the request's


async def test_fail_closed_before_save_failure_refuses_the_write(http, people, monkeypatch) -> None:  # noqa: ANN001
    def explode(data):  # noqa: ANN001, ANN202
        raise RuntimeError("x")

    monkeypatch.setitem(registry.HOOKS["normalize_no"], "fn", explode)
    failed = await http.post("/invoices", json=body(), headers=people["clerk"])
    assert failed.status_code == 500 and failed.json()["code"] == "hook_failed"
    assert (await http.get("/invoices", headers=people["clerk"])).json()["total"] == 0


async def test_hooks_do_not_run_on_delete(http, people, monkeypatch) -> None:  # noqa: ANN001
    created = await http.post("/invoices", json=body(), headers=people["clerk"])
    calls: list[str] = []
    for name in ("default_po", "normalize_no", "check_amounts", "audit_save", "notify_approved"):
        spy(monkeypatch, name, calls)
    deleted = await http.delete(f"/invoices/{created.json()['id']}", headers=people["admin"])
    assert deleted.status_code == 204, deleted.text
    assert calls == []


async def test_a_guard_hook_and_the_lifecycle_hooks_coexist(http, people) -> None:  # noqa: ANN001
    created = await http.post("/invoices", json=body("INV-5"), headers=people["clerk"])
    moved = await http.post(f"/invoices/{created.json()['id']}/transitions/submit", headers=people["clerk"])
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "approved"


async def test_runtime_helpers_are_importable() -> None:
    assert runtime.GRACE_SECONDS > 0 and sdk.__all__
