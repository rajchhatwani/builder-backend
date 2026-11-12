"""Scenario tests for the money pack's invoicing block (D7) in the generated `money_marketplace` project (copied
into the project's tests/ by tests/e2e/test_invoicing_stack.py, run against a real Postgres).

Multi-tenant spec: number prefix MKT-, 14 day terms, invoicing read roles admin + member, write role admin, tax
rates standard 2000 / reduced 500 / zero 0 bp, aging buckets 30 / 60 / 90. Proves: integer totals with half-even
tax per line, the state machine, immutable issued invoices (service and database), gapless numbers under 8
parallel issues, balanced ledger postings for issue / payment / void in the same transaction, partial payments
and refused overpayment (also under 8 parallel payments), idempotent payments, AR / AP aging in integers,
tenant isolation, roles. No 500 anywhere."""

import asyncio
import datetime as dt

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.db import engine, session_factory
from app.main import app
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
        "nobody": await sign_in(http, "nobody@example.com", roles=[], n=3, join="a@example.com"),
    }


ACCOUNTS = (("receivables", "asset"), ("payables", "liability"), ("sales", "income"), ("expenses", "expense"), ("tax", "liability"), ("bank", "asset"))


async def accounts(http: AsyncClient, who: dict[str, str], cur: str = "USD", suffix: bool = False) -> dict[str, str]:
    out = {}
    for code, kind in ACCOUNTS:
        name = f"{code}.{cur}" if suffix else code
        r = await http.post("/ledger/accounts", json={"code": name, "name": name, "kind": kind, "currency": cur}, headers=who)
        assert r.status_code == 201, r.text
        out[code] = r.json()["id"]
    return out


def L(desc: str, qty: int, price: int, rate: str | None = None) -> dict[str, object]:
    return {"description": desc, "quantity": qty, "unit_price_minor": price, "tax_rate": rate}


async def draft(http: AsyncClient, who: dict[str, str], lines: list[dict], kind: str = "receivable", cur: str = "USD", **extra: object) -> dict:
    r = await http.post("/invoices", json={"kind": kind, "counterparty": "Acme", "currency": cur, "lines": lines, **extra}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


async def issued(http: AsyncClient, who: dict[str, str], lines: list[dict], **kw: object) -> dict:
    inv = await draft(http, who, lines, **kw)  # type: ignore[arg-type]
    r = await http.post(f"/invoices/{inv['id']}/issue", headers=who)
    assert r.status_code == 200, r.text
    return r.json()


async def pay(http: AsyncClient, who: dict[str, str], inv_id: str, amount: int, key: str, **extra: object):  # noqa: ANN201
    return await http.post(f"/invoices/{inv_id}/payments", json={"idempotency_key": key, "amount_minor": amount, **extra}, headers=who)


async def scalar(sql: str, **params: object) -> object:
    async with session_factory() as session:
        return (await session.execute(sa.text(sql), params)).scalar_one()


async def balance_of(http: AsyncClient, who: dict[str, str], code: str) -> int:
    items = (await http.get("/ledger/balances", headers=who)).json()["items"]
    return next(i["balance_minor"] for i in items if i["code"] == code)


async def assert_books_balance() -> None:
    async with session_factory() as session:
        bad = (await session.execute(sa.text("select transaction_id from ledger_entries group by 1, currency having sum(amount) <> 0"))).all()
        assert bad == []
        assert (await session.execute(sa.text("select coalesce(sum(amount), 0) from ledger_entries"))).scalar_one() == 0


# hand-computed (half to even, per line): 10 @ reduced 5% = 0.5 -> 0; 30 -> 1.5 -> 2; 50 -> 2.5 -> 2; 3 x 333 = 999 @ 20% = 199.8 -> 200
LINES = [L("a", 1, 10, "reduced"), L("b", 1, 30, "reduced"), L("c", 1, 50, "reduced"), L("d", 3, 333, "standard"), L("e", 2, 7)]
NET, TAX = 10 + 30 + 50 + 999 + 14, 0 + 2 + 2 + 200 + 0


# --- totals, posting, state machine ------------------------------------------------------------------------


async def test_totals_are_integers_with_half_even_tax_per_line(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    inv = await draft(http, a, LINES)
    assert (inv["subtotal_minor"], inv["tax_minor"], inv["total_minor"]) == (NET, TAX, NET + TAX) == (1103, 204, 1307)
    assert [(x["net_minor"], x["tax_minor"], x["gross_minor"]) for x in inv["lines"]] == [(10, 0, 10), (30, 2, 32), (50, 2, 52), (999, 200, 1199), (14, 0, 14)]
    assert inv["status"] == "draft" and inv["number"] is None and inv["exponent"] == 2 and inv["outstanding_minor"] == NET + TAX
    assert set(inv) == {
        "id", "kind", "number", "status", "counterparty", "counterparty_ref", "currency", "exponent", "issue_date", "due_date", "notes",
        "subtotal_minor", "tax_minor", "total_minor", "paid_minor", "outstanding_minor", "issue_transaction_id", "void_transaction_id",
        "created_at", "issued_at", "voided_at", "lines", "payments",
    }
    assert all(type(inv[k]) is int for k in ("subtotal_minor", "tax_minor", "total_minor", "paid_minor"))
    # a draft is editable: lines are replaced and the totals follow
    patched = await http.patch(f"/invoices/{inv['id']}", json={"lines": [L("only", 5, 5, "zero")], "notes": "n"}, headers=a)
    assert patched.status_code == 200 and (patched.json()["total_minor"], patched.json()["tax_minor"]) == (25, 0)
    assert patched.json()["notes"] == "n" and len(patched.json()["lines"]) == 1
    listed = (await http.get("/invoices", params={"status": "draft"}, headers=a)).json()
    assert listed["total"] == 1 and (await http.get(f"/invoices/{inv['id']}", headers=a)).json()["id"] == inv["id"]


async def test_bad_requests_are_refused_without_writing(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    base = {"kind": "receivable", "counterparty": "Acme", "currency": "USD"}
    for body, code in (
        ({**base, "lines": [L("x", 1, 1, "nope")]}, "unknown_tax_rate"),
        ({**base, "currency": "GBP", "lines": [L("x", 1, 1)]}, "unsupported_currency"),
        ({**base, "lines": [L("x", 1, 1)], "issue_date": "2026-03-10", "due_date": "2026-03-01"}, "invalid_dates"),
        ({**base, "lines": [L("x", 2**52, 2**52)]}, None),
    ):
        r = await http.post("/invoices", json=body, headers=a)
        assert r.status_code == 422, r.text
        assert code is None or r.json()["code"] == code
        assert set(r.json()) >= {"code", "message", "details"}
    for line in (L("x", 1.5, 10), L("x", "1", 10), L("x", 1, 10.5), L("x", 0, 10), L("x", 1, -1), L("x", True, 1)):
        assert (await http.post("/invoices", json={**base, "lines": [line]}, headers=a)).status_code == 422
    assert (await http.post("/invoices", json={**base, "lines": []}, headers=a)).status_code == 422
    assert (await http.post("/invoices", json={**base, "lines": [L("x", 1, 1)], "extra": 1}, headers=a)).status_code == 422
    assert await scalar("select count(*) from invoices") == 0
    inv = await draft(http, a, [L("zero", 3, 0)])  # zero total: cannot be issued
    r = await http.post(f"/invoices/{inv['id']}/issue", headers=a)
    assert r.status_code == 422 and r.json()["code"] == "empty_invoice"
    r = await http.post(f"/invoices/{inv['id']}/issue", headers=a)
    assert (await http.post("/invoices/00000000-0000-0000-0000-000000000000/issue", headers=a)).status_code == 404


async def test_issue_posts_a_balanced_ledger_transaction_ar_and_ap(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    ids = await accounts(http, a)
    inv = await issued(http, a, LINES)
    assert inv["status"] == "issued" and inv["number"] == "MKT-000001"
    assert dt.date.fromisoformat(inv["due_date"]) - dt.date.fromisoformat(inv["issue_date"]) == dt.timedelta(days=14)
    tx = (await http.get(f"/ledger/transactions/{inv['issue_transaction_id']}", headers=a)).json()
    by_account = {e["account_id"]: e["amount_minor"] for e in tx["entries"]}
    assert by_account == {ids["receivables"]: 1307, ids["sales"]: -1103, ids["tax"]: -204} and tx["reference"] == "MKT-000001"
    bill = await issued(http, a, [L("hosting", 2, 500, "standard")], kind="payable")
    assert bill["number"] == "MKT-AP-000001" and (bill["subtotal_minor"], bill["tax_minor"], bill["total_minor"]) == (1000, 200, 1200)
    tx = (await http.get(f"/ledger/transactions/{bill['issue_transaction_id']}", headers=a)).json()
    assert {e["account_id"]: e["amount_minor"] for e in tx["entries"]} == {ids["payables"]: -1200, ids["expenses"]: 1000, ids["tax"]: 200}
    await assert_books_balance()
    # a missing ledger account is a precise 422, the invoice stays a draft and no number is used up
    eur = await draft(http, a, [L("x", 1, 100)], cur="EUR")
    r = await http.post(f"/invoices/{eur['id']}/issue", headers=a)
    assert r.status_code == 422 and r.json()["code"] == "account_missing" and r.json()["details"][0]["currency"] == "EUR"
    assert (await http.get(f"/invoices/{eur['id']}", headers=a)).json()["status"] == "draft"
    await accounts(http, a, "EUR", suffix=True)  # `<code>.<CUR>` is found for a currency the plain code does not carry
    again = await http.post(f"/invoices/{eur['id']}/issue", headers=a)
    assert again.status_code == 200 and again.json()["number"] == "MKT-000002"
    await assert_books_balance()


async def test_state_machine_and_immutability(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    inv = await issued(http, a, [L("x", 1, 1000)])
    for call in (
        http.patch(f"/invoices/{inv['id']}", json={"notes": "changed"}, headers=a),
        http.patch(f"/invoices/{inv['id']}", json={"lines": [L("y", 1, 1)]}, headers=a),
    ):
        r = await call
        assert r.status_code == 409 and r.json()["code"] == "invoice_immutable"
    again = await http.post(f"/invoices/{inv['id']}/issue", headers=a)
    assert again.status_code == 409 and again.json()["code"] == "invalid_transition"
    # the database refuses it as well, behind the API
    for sql in (
        "update invoices set total_minor = 1, subtotal_minor = 1 where status = 'issued'",
        "update invoices set counterparty = 'Other' where status = 'issued'",
        "update invoices set number = 'MKT-999999' where status = 'issued'",
        "update invoice_lines set quantity = 2",
        "delete from invoice_lines",
    ):
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            async with engine.begin() as conn:
                await conn.execute(sa.text(sql))
    # a draft cannot take a payment; a part-paid invoice cannot be voided; a paid one is frozen
    d = await draft(http, a, [L("x", 1, 100)])
    r = await pay(http, a, d["id"], 10, "k")
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"
    assert (await pay(http, a, inv["id"], 400, "p1")).json()["status"] == "partially_paid"
    r = await http.post(f"/invoices/{inv['id']}/void", headers=a)
    assert r.status_code == 409 and r.json()["code"] == "has_payments"
    paid = (await pay(http, a, inv["id"], 600, "p2")).json()
    assert paid["status"] == "paid" and paid["outstanding_minor"] == 0
    assert (await http.post(f"/invoices/{inv['id']}/void", headers=a)).json()["code"] == "invalid_transition"
    with pytest.raises(sa.exc.DBAPIError, match="cannot change"):
        async with engine.begin() as conn:
            await conn.execute(sa.text("update invoices set paid_minor = 0 where status = 'paid'"))
    # a draft can be voided (no ledger posting, no number); a void invoice is final and the call repeats safely
    v = await http.post(f"/invoices/{d['id']}/void", json={"reason": "typo"}, headers=a)
    assert v.status_code == 200 and v.json()["status"] == "void" and v.json()["number"] is None and v.json()["void_transaction_id"] is None
    v2 = await http.post(f"/invoices/{d['id']}/void", headers=a)
    assert v2.status_code == 200 and v2.headers["Idempotent-Replayed"] == "true"
    assert (await http.patch(f"/invoices/{d['id']}", json={"notes": "z"}, headers=a)).status_code == 409


async def test_void_posts_a_ledger_reversal(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    inv = await issued(http, a, [L("x", 2, 500, "standard")])
    assert await balance_of(http, a, "receivables") == 1200
    v = (await http.post(f"/invoices/{inv['id']}/void", json={"reason": "cancelled"}, headers=a)).json()
    assert v["status"] == "void" and v["number"] == inv["number"] and v["void_transaction_id"]  # the number is kept: no gap
    rev = (await http.get(f"/ledger/transactions/{v['void_transaction_id']}", headers=a)).json()
    assert rev["reverses_id"] == inv["issue_transaction_id"]
    for code in ("receivables", "sales", "tax"):
        assert await balance_of(http, a, code) == 0
    await assert_books_balance()


# --- payments ----------------------------------------------------------------------------------------------


async def test_partial_payments_overpayment_and_idempotency(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    inv = await issued(http, a, [L("x", 1, 1000)])
    r = await pay(http, a, inv["id"], 300, "k1", reference="BANK-1", paid_on="2026-03-02")
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["paid_minor"], body["outstanding_minor"]) == ("partially_paid", 300, 700)
    assert body["payments"][0]["amount_minor"] == 300 and body["payments"][0]["paid_on"] == "2026-03-02"
    tx = (await http.get(f"/ledger/transactions/{body['payments'][0]['ledger_transaction_id']}", headers=a)).json()
    assert sorted(e["amount_minor"] for e in tx["entries"]) == [-300, 300] and tx["reference"] == inv["number"]
    replay = await pay(http, a, inv["id"], 300, "k1", reference="BANK-1", paid_on="2026-03-02")
    assert replay.status_code == 200 and replay.headers["Idempotent-Replayed"] == "true" and replay.json()["paid_minor"] == 300
    assert (await pay(http, a, inv["id"], 301, "k1", reference="BANK-1", paid_on="2026-03-02")).json()["code"] == "idempotency_conflict"
    other = await issued(http, a, [L("y", 1, 50)])
    assert (await pay(http, a, other["id"], 300, "k1", reference="BANK-1", paid_on="2026-03-02")).status_code == 409  # key used for another invoice
    over = await pay(http, a, inv["id"], 701, "k2")
    assert over.status_code == 422 and over.json()["code"] == "overpayment" and over.json()["details"][0]["outstanding_minor"] == 700
    for bad in (0, -5, 1.5, "5"):
        assert (await pay(http, a, inv["id"], bad, "bad")).status_code == 422  # type: ignore[arg-type]
    assert (await pay(http, a, inv["id"], 700, "k3")).json()["status"] == "paid"
    assert (await pay(http, a, inv["id"], 1, "k4")).json()["code"] == "invalid_transition"
    assert await balance_of(http, a, "bank") == 1000 and await balance_of(http, a, "receivables") == 50  # the second invoice is open
    assert await scalar("select count(*) from invoice_payments") == 2
    await assert_books_balance()


async def test_ap_payment_mirrors_the_ar_postings(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    ids = await accounts(http, a)
    bill = await issued(http, a, [L("rent", 1, 800)], kind="payable")
    paid = (await pay(http, a, bill["id"], 800, "p")).json()
    assert paid["status"] == "paid"
    tx = (await http.get(f"/ledger/transactions/{paid['payments'][0]['ledger_transaction_id']}", headers=a)).json()
    assert {e["account_id"]: e["amount_minor"] for e in tx["entries"]} == {ids["payables"]: 800, ids["bank"]: -800}
    assert await balance_of(http, a, "payables") == 0 and await balance_of(http, a, "bank") == -800
    await assert_books_balance()


async def test_eight_parallel_issues_give_gapless_distinct_numbers(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    drafts = [await draft(http, a, [L("x", 1, 100 + n)]) for n in range(8)]
    results = await asyncio.gather(*(http.post(f"/invoices/{d['id']}/issue", headers=a) for d in drafts))
    assert [r.status_code for r in results] == [200] * 8
    numbers = sorted(r.json()["number"] for r in results)
    assert numbers == [f"MKT-{n:06d}" for n in range(1, 9)]
    assert await scalar("select last_value from invoice_counters where kind = 'receivable'") == 8
    assert await scalar("select count(distinct number) from invoices") == 8
    await assert_books_balance()
    # 8 more, half of them failing (EUR has no accounts): the failures use up no number
    ok = [await draft(http, a, [L("x", 1, 10)]) for _ in range(4)]
    bad = [await draft(http, a, [L("x", 1, 10)], cur="EUR") for _ in range(4)]
    results = await asyncio.gather(*(http.post(f"/invoices/{d['id']}/issue", headers=a) for d in ok + bad))
    assert sorted(r.status_code for r in results) == [200] * 4 + [422] * 4
    nums = sorted(r.json()["number"] for r in results if r.status_code == 200)
    assert nums == [f"MKT-{n:06d}" for n in range(9, 13)]
    assert await scalar("select last_value from invoice_counters where kind = 'receivable'") == 12
    await assert_books_balance()


async def test_eight_parallel_payments_never_overpay(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    inv = await issued(http, a, [L("x", 1, 1000)])
    results = await asyncio.gather(*(pay(http, a, inv["id"], 1000, f"par-{n}") for n in range(8)))
    assert sorted(r.status_code for r in results) == [201] + [409] * 7  # the losers find the invoice already paid
    assert {r.json()["code"] for r in results if r.status_code == 409} == {"invalid_transition"}
    assert await scalar("select paid_minor from invoices where id = :i", i=inv["id"]) == 1000
    inv2 = await issued(http, a, [L("x", 1, 1000)])
    same = await asyncio.gather(*(pay(http, a, inv2["id"], 250, "one-key") for _ in range(8)))
    assert sorted(r.status_code for r in same) == [200] * 7 + [201]
    assert await scalar("select count(*) from invoice_payments where invoice_id = :i", i=inv2["id"]) == 1
    inv3 = await issued(http, a, [L("x", 1, 1000)])
    big = await asyncio.gather(*(pay(http, a, inv3["id"], 600, f"big-{n}") for n in range(8)))
    assert sorted(r.status_code for r in big) == [201] + [422] * 7  # 400 left after the first: 600 is an overpayment
    assert {r.json()["code"] for r in big if r.status_code == 422} == {"overpayment"}
    assert await scalar("select paid_minor from invoices where id = :i", i=inv3["id"]) == 600
    quarter = await asyncio.gather(*(pay(http, a, inv2["id"], 250, f"q-{n}") for n in range(8)))
    assert sorted(r.status_code for r in quarter) == [201] * 3 + [409] * 5  # 750 left: exactly three payments fit, the rest meet a paid invoice
    assert await scalar("select status from invoices where id = :i", i=inv2["id"]) == "paid"
    await assert_books_balance()


# --- aging -------------------------------------------------------------------------------------------------


async def test_aging_buckets_by_days_past_due_per_currency_in_integers(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    await accounts(http, a, "EUR", suffix=True)
    as_of = "2026-06-30"
    due = {  # due date -> (amount, days past due on 2026-06-30)
        "2026-07-05": 1, "2026-06-30": 2, "2026-06-29": 4, "2026-05-31": 8, "2026-05-30": 16, "2026-04-01": 32, "2026-03-31": 64,
    }
    for day, amount in due.items():
        await issued(http, a, [L("x", 1, amount)], issue_date="2026-01-01", due_date=day)
    await issued(http, a, [L("e", 1, 1000)], cur="EUR", issue_date="2026-01-01", due_date="2026-06-01")  # 29 days
    part = await issued(http, a, [L("p", 1, 100)], issue_date="2026-01-01", due_date="2026-06-20")  # 10 days, 60 paid
    await pay(http, a, part["id"], 60, "part")
    done = await issued(http, a, [L("d", 1, 5000)], issue_date="2026-01-01", due_date="2026-01-10")
    await pay(http, a, done["id"], 5000, "done")  # paid: not in the report
    gone = await issued(http, a, [L("v", 1, 7000)], issue_date="2026-01-01", due_date="2026-01-10")
    await http.post(f"/invoices/{gone['id']}/void", headers=a)  # void: not in the report
    await draft(http, a, [L("dr", 1, 9000)], issue_date="2026-01-01", due_date="2026-01-10")  # draft: not in the report
    await issued(http, a, [L("ap", 1, 333)], kind="payable", issue_date="2026-01-01", due_date="2026-06-01")
    r = await http.get("/invoices/aging", params={"as_of": as_of}, headers=a)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["kind"] == "receivable" and rep["as_of"] == as_of and rep["bucket_days"] == [30, 60, 90]
    usd, eur = rep["currencies"]
    assert (usd["currency"], eur["currency"]) == ("USD", "EUR") or (usd["currency"], eur["currency"]) == ("EUR", "USD")
    usd, eur = (usd, eur) if usd["currency"] == "USD" else (eur, usd)
    assert [(b["label"], b["from_days"], b["to_days"]) for b in usd["buckets"]] == [("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("91+", 91, None)]
    # current: due 2026-07-05 (1) and due today (2); 1-30: 4 (1 day), 8 (30 days), 40 (part-paid, 10 days); 31-60: 16; 61-90: 32; 91+: 64
    assert (usd["current_minor"], usd["current_count"]) == (3, 2)
    assert [(b["amount_minor"], b["count"]) for b in usd["buckets"]] == [(4 + 8 + 40, 3), (16, 1), (32, 1), (64, 1)]
    assert usd["total_minor"] == 3 + 52 + 16 + 32 + 64 and usd["count"] == 8
    assert eur["current_minor"] == 0 and [(b["amount_minor"], b["count"]) for b in eur["buckets"]] == [(1000, 1), (0, 0), (0, 0), (0, 0)]
    for cur in (usd, eur):
        assert all(type(v) is int for v in (cur["current_minor"], cur["total_minor"], *(b["amount_minor"] for b in cur["buckets"])))
    ap = (await http.get("/invoices/aging", params={"as_of": as_of, "kind": "payable"}, headers=a)).json()
    assert [(c["currency"], c["total_minor"]) for c in ap["currencies"]] == [("USD", 333)]
    assert (await http.get("/invoices/aging", params={"as_of": "2026-01-05"}, headers=a)).json()["currencies"][0]["current_minor"] > 0
    assert (await http.get("/invoices/aging", params={"kind": "other"}, headers=a)).status_code == 422


# --- isolation and roles -----------------------------------------------------------------------------------


async def test_tenants_are_isolated_and_roles_are_enforced(http, people) -> None:  # noqa: ANN001
    a, member, b, nobody = people["a"], people["a_member"], people["b"], people["nobody"]
    await accounts(http, a)
    inv = await issued(http, a, [L("x", 1, 100)])
    assert (await http.get("/invoices", headers=b)).json()["total"] == 0
    for method, path, body in (
        ("get", f"/invoices/{inv['id']}", None),
        ("patch", f"/invoices/{inv['id']}", {"notes": "x"}),
        ("post", f"/invoices/{inv['id']}/issue", None),
        ("post", f"/invoices/{inv['id']}/void", None),
        ("post", f"/invoices/{inv['id']}/payments", {"idempotency_key": "k", "amount_minor": 1}),
    ):
        assert (await http.request(method, path, json=body, headers=b)).status_code == 404, path
    assert (await http.get("/invoices/aging", headers=b)).json()["currencies"] == []
    # tenant b has no ledger accounts of its own: it cannot post to tenant a's
    mine = await draft(http, b, [L("x", 1, 10)])
    assert (await http.post(f"/invoices/{mine['id']}/issue", headers=b)).json()["code"] == "account_missing"
    assert (await http.get(f"/invoices/{inv['id']}", headers=member)).status_code == 200  # may read
    assert (await http.get("/invoices/aging", headers=member)).status_code == 200
    assert (await http.post("/invoices", json={"kind": "receivable", "counterparty": "x", "currency": "USD", "lines": [L("x", 1, 1)]}, headers=member)).status_code == 403
    assert (await pay(http, member, inv["id"], 1, "m")).status_code == 403
    assert (await http.post(f"/invoices/{inv['id']}/issue", headers=member)).status_code == 403
    assert (await http.get("/invoices", headers=nobody)).status_code == 403
    assert (await http.get("/invoices")).status_code == 401
    assert (await pay(http, {}, inv["id"], 1, "anon")).status_code == 401
    assert await scalar("select count(*) from invoices") == 2


async def test_the_ledger_cannot_reverse_an_invoice_posting_and_patch_null_is_refused(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await accounts(http, a)
    inv = await issued(http, a, [L("x", 1, 1000)])
    paid = (await pay(http, a, inv["id"], 400, "p")).json()
    for tx in (inv["issue_transaction_id"], paid["payments"][0]["ledger_transaction_id"]):
        r = await http.post(f"/ledger/transactions/{tx}/reverse", json={"idempotency_key": f"rev-{tx}"}, headers=a)
        assert r.status_code == 409 and r.json()["code"] == "managed_transaction", r.text
    assert (await http.get(f"/invoices/{inv['id']}", headers=a)).json()["status"] == "partially_paid"
    d = await draft(http, a, [L("y", 1, 5)])
    for field in ("counterparty", "currency"):
        r = await http.patch(f"/invoices/{d['id']}", json={field: None}, headers=a)
        assert r.status_code == 422 and r.json()["code"] == "invalid_field", r.text
    # a retry of a payment without paid_on replays even if the date moved on in between
    first = await pay(http, a, inv["id"], 100, "nodate")
    assert first.status_code == 201
    assert (await pay(http, a, inv["id"], 100, "nodate")).status_code == 200
