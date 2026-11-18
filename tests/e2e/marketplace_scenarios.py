"""Scenario tests for the neutral marketplace payout flow in the generated `money_marketplace` project (copied
into the project's tests/ by tests/e2e/test_marketplace_payout_stack.py, run against a real Postgres).

Buyers pay the platform, the platform keeps a commission of 1250 basis points, the sellers get the rest.
Proves, end to end: sale -> invoice issued -> payment -> split (largest remainder) -> payout -> bank statement
import -> reconciliation matches; the final ledger balances sum to zero per currency and the commission and
seller balances are exact integers; 8 parallel payouts with one key make exactly one payout; payout refusals
(unpaid, payable, unknown, missing account); tenant isolation and roles."""

import asyncio

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.db import session_factory
from app.main import app
from app.money import currency as money
from tests._auth_support import outbox, sign_in  # noqa: F401


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "a": await sign_in(http, "a@example.com", roles=["admin"], n=0),
        "a_member": await sign_in(http, "a_member@example.com", roles=["member"], n=1, join="a@example.com"),
        "b": await sign_in(http, "b@example.com", roles=["admin"], n=2),
    }


ACCOUNTS = (
    ("receivables", "asset"), ("payables", "liability"), ("sales", "income"), ("expenses", "expense"),
    ("tax", "liability"), ("bank", "asset"), ("seller_payable", "liability"), ("commission", "income"),
)
COMMISSION_BP = 1250


async def accounts(http: AsyncClient, who: dict[str, str], skip: tuple[str, ...] = ()) -> dict[str, str]:
    out = {}
    for code, kind in ACCOUNTS:
        if code in skip:
            continue
        r = await http.post("/ledger/accounts", json={"code": code, "name": code, "kind": kind, "currency": "USD"}, headers=who)
        assert r.status_code == 201, r.text
        out[code] = r.json()["id"]
    return out


async def sale(http: AsyncClient, who: dict[str, str], net: int, rate: str | None = None, paid: bool = True, key: str = "") -> dict:
    """A buyer's invoice for `net` (tax on top for a named rate), issued, and paid in full unless told otherwise."""
    line = {"description": "goods", "quantity": 1, "unit_price_minor": net, "tax_rate": rate}
    r = await http.post("/invoices", json={"kind": "receivable", "counterparty": "Buyer", "currency": "USD", "lines": [line]}, headers=who)
    assert r.status_code == 201, r.text
    r = await http.post(f"/invoices/{r.json()['id']}/issue", headers=who)
    assert r.status_code == 200, r.text
    inv = r.json()
    if paid:
        r = await http.post(f"/invoices/{inv['id']}/payments", json={"idempotency_key": f"pay-{key or inv['number']}", "amount_minor": inv["total_minor"]}, headers=who)
        assert r.status_code == 201, r.text
        inv = r.json()
        assert inv["status"] == "paid"
    return inv


async def payout(http: AsyncClient, who: dict[str, str], inv_id: str, seller: str, key: str):  # noqa: ANN201
    return await http.post("/payouts/run", json={"idempotency_key": key, "invoice_id": inv_id, "seller": seller}, headers=who)


async def balances(http: AsyncClient, who: dict[str, str]) -> dict[str, int]:
    body = (await http.get("/ledger/balances", headers=who)).json()
    assert all(t["sum_minor"] == 0 for t in body["totals"])  # the books balance per currency
    return {i["code"]: i["balance_minor"] for i in body["items"]}


async def scalar(sql: str, **params: object) -> object:
    async with session_factory() as session:
        return (await session.execute(sa.text(sql), params)).scalar_one()


async def assert_books_balance() -> None:
    async with session_factory() as session:
        bad = (await session.execute(sa.text("select transaction_id from ledger_entries group by 1, currency having sum(amount) <> 0"))).all()
        assert bad == []
        assert (await session.execute(sa.text("select coalesce(sum(amount), 0) from ledger_entries"))).scalar_one() == 0


def stmt_line(ext: str, amount: int, ref: str | None, day: str = "2026-03-01") -> dict[str, object]:
    return {"external_id": ext, "date": day, "amount_minor": amount, "currency": "USD", "reference": ref}


# --- the whole flow ----------------------------------------------------------------------------------------


async def test_split_uses_largest_remainder_and_sums_exactly() -> None:
    # the commission is 12.50 % of the net: 10001 * 0.125 = 1250.125 -> the odd unit goes to the seller
    assert money.allocate(10_001, [COMMISSION_BP, 10_000 - COMMISSION_BP]) == [1250, 8751]
    assert money.allocate(5_000, [COMMISSION_BP, 8_750]) == [625, 4_375]
    assert money.allocate(3, [COMMISSION_BP, 8_750]) == [0, 3]


async def test_sale_to_payout_to_bank_statement_to_reconciliation(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    s1 = await sale(http, a, 10_001, "standard")  # net 10001, tax 2000 (2000.2 half-even), buyer pays 12001
    assert (s1["subtotal_minor"], s1["tax_minor"], s1["total_minor"]) == (10_001, 2_000, 12_001)
    s2 = await sale(http, a, 5_000)
    s3 = await sale(http, a, 3)
    results = []
    for n, s_ in ((1, s1), (2, s2), (3, s3)):
        r = await payout(http, a, s_["id"], f"seller-{n}", f"po-{n}")
        assert r.status_code == 201, r.text
        results.append(r.json())
    again = await payout(http, a, s1["id"], "seller-1", "po-1")  # the same call again is a replay, not a second payout
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true" and again.json() == results[0]
    assert [(p["gross_minor"], p["commission_minor"], p["seller_minor"]) for p in results] == [(10_001, 1_250, 8_751), (5_000, 625, 4_375), (3, 0, 3)]
    assert all(p["commission_bp"] == COMMISSION_BP and p["currency"] == "USD" for p in results)
    assert all(p["gross_minor"] == p["commission_minor"] + p["seller_minor"] for p in results)
    assert set(results[0]) == {"id", "invoice_id", "seller", "currency", "gross_minor", "commission_bp", "commission_minor", "seller_minor", "split_transaction_id", "payout_transaction_id", "created_at"}
    # the books: exact integers, sum to zero
    bal = await balances(http, a)
    assert bal == {
        "receivables": 0,
        "sales": 0,  # credited on issue, debited by the split
        "tax": -2_000,
        "bank": 12_001 + 5_000 + 3 - 8_751 - 4_375 - 3,
        "commission": -(1_250 + 625 + 0),
        "seller_payable": 0,  # credited by the split, debited by the payout
        "payables": 0,
        "expenses": 0,
    }
    assert bal["bank"] == 3_875
    assert sum(bal.values()) == 0
    totals = (await http.get("/payouts/totals", headers=a)).json()
    assert {t["seller"]: (t["gross_minor"], t["commission_minor"], t["seller_minor"], t["count"]) for t in totals} == {
        "seller-1": (10_001, 1_250, 8_751, 1), "seller-2": (5_000, 625, 4_375, 1), "seller-3": (3, 0, 3, 1),
    }
    assert sum(t["commission_minor"] for t in totals) == 1_875 and sum(t["seller_minor"] for t in totals) == 13_129
    assert (await http.get("/payouts/totals", params={"seller": "seller-2"}, headers=a)).json()[0]["seller_minor"] == 4_375
    one = (await http.get(f"/payouts/{results[0]['id']}", headers=a)).json()
    assert one == results[0]
    assert (await http.get("/payouts", params={"invoice_id": s2["id"]}, headers=a)).json()["total"] == 1
    # the split and payout postings are balanced ledger transactions
    split = (await http.get(f"/ledger/transactions/{results[0]['split_transaction_id']}", headers=a)).json()
    assert sorted(e["amount_minor"] for e in split["entries"]) == [-8_751, -1_250, 10_001]
    pay_tx = (await http.get(f"/ledger/transactions/{results[0]['payout_transaction_id']}", headers=a)).json()
    assert sorted(e["amount_minor"] for e in pay_tx["entries"]) == [-8_751, 8_751] and pay_tx["reference"] == f"PAYOUT-{results[0]['id']}"
    assert results[2]["commission_minor"] == 0  # a zero commission leaves no zero ledger entry
    zero = (await http.get(f"/ledger/transactions/{results[2]['split_transaction_id']}", headers=a)).json()
    assert sorted(e["amount_minor"] for e in zero["entries"]) == [-3, 3]
    await assert_books_balance()

    # the bank statement: three receipts (referenced by invoice number), three payouts (referenced by payout id), a fee
    bank = next(i for i in (await http.get("/ledger/accounts", headers=a)).json()["items"] if i["code"] == "bank")["id"]
    lines = [
        stmt_line("S1", 12_001, s1["number"]), stmt_line("S2", 5_000, s2["number"]), stmt_line("S3", 3, s3["number"]),
        stmt_line("S4", -8_751, f"PAYOUT-{results[0]['id']}"), stmt_line("S5", -4_375, f"PAYOUT-{results[1]['id']}"),
        stmt_line("S6", -3, f"PAYOUT-{results[2]['id']}"), stmt_line("S7", -150, "FEE"),
    ]
    imp = await http.post("/reconciliation/runs", json={"idempotency_key": "march", "account_id": bank, "lines": lines, "name": "March"}, headers=a)
    assert imp.status_code == 201, imp.text
    run = imp.json()
    m = await http.post(f"/reconciliation/runs/{run['id']}/match", headers=a)
    assert m.json() == {"new_matches": 6, "matched_count": 6, "unmatched_line_count": 1, "entries_truncated": False}
    res = (await http.get(f"/reconciliation/runs/{run['id']}/results", headers=a)).json()
    payout_lines = {p["line"]["external_id"]: p for p in res["matched"] if p["line"]["external_id"] in ("S4", "S5", "S6")}
    assert {k: (v["match"]["method"], v["match"]["diff_minor"], v["entry"]["amount_minor"]) for k, v in payout_lines.items()} == {
        "S4": ("exact_reference", 0, -8_751), "S5": ("exact_reference", 0, -4_375), "S6": ("exact_reference", 0, -3),
    }
    assert all(p["match"]["method"] == "exact_reference" and p["match"]["diff_minor"] == 0 for p in res["matched"])
    assert [x["external_id"] for x in res["unmatched_lines"]] == ["S7"] and res["unmatched_entries"] == []
    summary = res["summary"]
    assert (summary["statement_total_minor"], summary["matched_lines_minor"], summary["unmatched_lines_minor"], summary["difference_minor"]) == (
        3_875 - 150, 3_875, -150, -150,
    )
    closed = (await http.post(f"/reconciliation/runs/{run['id']}/close", headers=a)).json()
    assert closed["status"] == "closed" and closed["summary"]["difference_minor"] == -150
    assert bal["bank"] == summary["matched_entries_minor"]  # the ledger's bank balance is exactly what the statement confirmed
    await assert_books_balance()


async def test_eight_parallel_payouts_with_one_key_make_exactly_one_payout(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    inv = await sale(http, a, 10_001)
    results = await asyncio.gather(*(payout(http, a, inv["id"], "seller-1", "one-key") for _ in range(8)))
    assert sorted(r.status_code for r in results) == [200] * 7 + [201]
    assert len({r.json()["id"] for r in results}) == 1
    assert await scalar("select count(*) from money_payouts") == 1
    assert await scalar("select count(*) from ledger_transactions where idempotency_key like 'payout:%'") == 2  # split + payout, once
    bal = await balances(http, a)
    assert (bal["commission"], bal["seller_payable"], bal["bank"], bal["sales"]) == (-1_250, 0, 10_001 - 8_751, 0)
    # 8 different keys for the SAME invoice: the invoice is paid out once, the rest are refused (no 500)
    inv2 = await sale(http, a, 5_000)
    many = await asyncio.gather(*(payout(http, a, inv2["id"], "seller-2", f"key-{n}") for n in range(8)))
    assert sorted(r.status_code for r in many) == [201] + [409] * 7
    assert {r.json()["code"] for r in many if r.status_code == 409} == {"already_paid_out"}
    assert await scalar("select count(*) from money_payouts") == 2
    # 8 invoices, 8 sellers, in parallel: every payout is made, the books still balance
    invs = [await sale(http, a, 1_000 + n * 7, key=f"m{n}") for n in range(8)]
    parallel = await asyncio.gather(*(payout(http, a, i["id"], f"seller-{n}", f"par-{n}") for n, i in enumerate(invs)))
    assert [r.status_code for r in parallel] == [201] * 8
    assert all(r.json()["gross_minor"] == r.json()["commission_minor"] + r.json()["seller_minor"] for r in parallel)
    await assert_books_balance()
    assert (await balances(http, a))["seller_payable"] == 0


async def test_payout_refusals_leave_no_trace(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a, skip=("commission",))
    unpaid = await sale(http, a, 1_000, paid=False)
    r = await payout(http, a, unpaid["id"], "s", "k1")
    assert r.status_code == 409 and r.json()["code"] == "invoice_not_paid"
    bill = await http.post("/invoices", json={"kind": "payable", "counterparty": "Vendor", "currency": "USD", "lines": [{"description": "x", "quantity": 1, "unit_price_minor": 100}]}, headers=a)
    assert (await payout(http, a, bill.json()["id"], "s", "k2")).json()["code"] == "invalid_invoice"
    assert (await payout(http, a, "00000000-0000-0000-0000-000000000000", "s", "k3")).status_code == 404
    paid = await sale(http, a, 1_000)
    r = await payout(http, a, paid["id"], "s", "k4")  # the commission account does not exist yet
    assert r.status_code == 422 and r.json()["code"] == "account_missing" and set(r.json()) == {"code", "message", "details"}
    assert await scalar("select count(*) from money_payouts") == 0
    assert await scalar("select count(*) from ledger_transactions where idempotency_key like 'payout:%'") == 0
    await http.post("/ledger/accounts", json={"code": "commission", "name": "c", "kind": "income", "currency": "USD"}, headers=a)
    ok = await payout(http, a, paid["id"], "s", "k4")
    assert ok.status_code == 201
    assert (await payout(http, a, paid["id"], "other-seller", "k4")).json()["code"] == "idempotency_conflict"
    for bad in ({"idempotency_key": "k", "invoice_id": paid["id"], "seller": ""}, {"idempotency_key": "k", "invoice_id": "nope", "seller": "s"}, {"invoice_id": paid["id"], "seller": "s"}):
        assert (await http.post("/payouts/run", json=bad, headers=a)).status_code == 422
    await assert_books_balance()


async def test_payouts_are_tenant_isolated_and_role_checked(http, people) -> None:  # noqa: ANN001
    a, member, b = people["a"], people["a_member"], people["b"]
    await accounts(http, a)
    inv = await sale(http, a, 2_000)
    made = (await payout(http, a, inv["id"], "s", "k")).json()
    assert (await payout(http, b, inv["id"], "s", "kb")).status_code == 404
    assert (await http.get("/payouts", headers=b)).json()["total"] == 0 and (await http.get("/payouts/totals", headers=b)).json() == []
    assert (await http.get(f"/payouts/{made['id']}", headers=b)).status_code == 404
    assert (await http.get(f"/payouts/{made['id']}", headers=member)).status_code == 200  # may read
    assert (await payout(http, member, inv["id"], "s", "km")).status_code == 403  # may not run
    assert (await http.get("/payouts")).status_code == 401
    assert (await payout(http, {}, inv["id"], "s", "anon")).status_code == 401
    assert await scalar("select count(*) from money_payouts") == 1
