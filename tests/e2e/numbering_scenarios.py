"""Scenario tests for the generated `numbering` project (multi-tenant orders). Copied into the project's
tests/ folder by tests/e2e/test_numbering_stack.py and run against a real Postgres.

Rules under test: numbers are assigned by the platform inside the create transaction (shared, per-year and
bare-counter sequences; parallel creates across tenants get distinct consecutive numbers; a number sent by
the caller is ignored); a guard that reads `settings.approval_threshold` uses the CURRENT value of the
record's own tenant (one tenant's change never reaches the other) and a change needs no regeneration.
"""

import asyncio
import datetime as dt
import re

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.main import app


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def tenants(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "a": await sign_in(http, "a-admin@example.com", roles=["admin"], n=0),
        "b": await sign_in(http, "b-admin@example.com", roles=["admin"], n=1),
    }


async def place(http, who, total="500.00", **extra):  # noqa: ANN001, ANN201
    return await http.post("/orders", json={"customer": "Acme", "total": total, **extra}, headers=who)


def count(value: object) -> int:
    match = re.search(r"(\d+)$", str(value))
    assert match is not None, value
    return int(match.group(1))


async def test_numbers_are_distinct_and_consecutive_across_tenants(http, tenants) -> None:  # noqa: ANN001
    made = await asyncio.gather(*(place(http, tenants["a" if i % 2 else "b"]) for i in range(16)))
    assert {r.status_code for r in made} == {201}, [r.text for r in made]
    rows = [r.json() for r in made]
    year = dt.datetime.now(dt.UTC).year
    assert sorted(count(r["invoice_no"]) for r in rows) == list(range(1, 17))
    assert len({r["invoice_no"] for r in rows}) == 16
    assert all(re.fullmatch(rf"INV-\d{{5}}", r["invoice_no"]) for r in rows)
    assert all(re.fullmatch(rf"ORD-{year}-\d{{4}}", r["order_no"]) for r in rows)
    assert sorted(r["ticket_no"] for r in rows) == list(range(100, 116))  # a bare counter is a number


async def test_a_number_sent_by_the_caller_is_ignored_and_cannot_be_changed(http, tenants) -> None:  # noqa: ANN001
    forged = await place(http, tenants["a"], invoice_no="INV-99999", order_no="X", ticket_no=7)
    assert forged.status_code == 201, forged.text
    row = forged.json()
    assert row["invoice_no"] == "INV-00001" and row["ticket_no"] == 100
    patched = await http.patch(f"/orders/{row['id']}", json={"invoice_no": "INV-00042", "customer": "New"},
                               headers=tenants["a"])
    assert patched.status_code == 200 and patched.json()["invoice_no"] == "INV-00001"
    assert patched.json()["customer"] == "New"


async def test_the_guard_reads_the_current_setting_of_the_records_own_tenant(http, tenants) -> None:  # noqa: ANN001
    put = lambda who, value: http.put("/config/settings/approval_threshold", json={"value": value}, headers=who)  # noqa: E731
    stage = lambda r: r.json()["stage"]  # noqa: E731
    default = await place(http, tenants["a"], "500.00")
    assert stage(default) == "auto_approved"  # default threshold 1000
    assert (await put(tenants["a"], 100)).status_code == 200
    a_low = await place(http, tenants["a"], "500.00")
    b_same = await place(http, tenants["b"], "500.00")
    assert stage(a_low) == "needs_review"  # tenant A lowered its threshold ...
    assert stage(b_same) == "auto_approved"  # ... tenant B did not feel it
    assert (await put(tenants["a"], 10000)).status_code == 200
    assert stage(await place(http, tenants["a"], "5000.00")) == "auto_approved"  # takes effect at once
    assert stage(await place(http, tenants["b"], "5000.00")) == "needs_review"  # B is still at 1000
