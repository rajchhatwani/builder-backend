"""Scenario tests for the money pack's reconciliation block (D6) in the generated `money_marketplace` project
(copied into the project's tests/ by tests/e2e/test_reconciliation_stack.py, run against a real Postgres).

Multi-tenant spec: reconciliation read roles admin + member, run role admin, tolerance 5 minor units. Proves:
import (idempotent), matcher (reference first, exact, tolerance), manual match and un-match, one-to-one even under
8 parallel runs / matches (and straight in the database), results and a closed run with an integer summary,
tenant isolation and roles. No 500 anywhere."""

import asyncio

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


async def account(http: AsyncClient, who: dict[str, str], code: str, cur: str = "USD", kind: str = "asset") -> str:
    r = await http.post("/ledger/accounts", json={"code": code, "name": code.title(), "kind": kind, "currency": cur}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def book(http: AsyncClient, who: dict[str, str], key: str, bank: str, other: str, amount: int, reference: str | None = None) -> dict:
    """Debit `bank` by `amount` (credit when negative) against `other`; returns the ledger transaction."""
    body = {
        "idempotency_key": key,
        "reference": reference,
        "entries": [{"account_id": bank, "amount_minor": amount}, {"account_id": other, "amount_minor": -amount}],
    }
    r = await http.post("/ledger/transactions", json=body, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


def line(ext: str, amount: int, ref: str | None = None, day: str = "2026-03-01", cur: str = "USD") -> dict[str, object]:
    return {"external_id": ext, "date": day, "amount_minor": amount, "currency": cur, "reference": ref}


async def import_run(http: AsyncClient, who: dict[str, str], key: str, account_id: str, lines: list[dict], **extra: object):  # noqa: ANN201
    return await http.post(
        "/reconciliation/runs", json={"idempotency_key": key, "account_id": account_id, "lines": lines, **extra}, headers=who
    )


async def scalar(sql: str, **params: object) -> object:
    async with session_factory() as session:
        return (await session.execute(sa.text(sql), params)).scalar_one()


async def setup(http: AsyncClient, a: dict[str, str]) -> tuple[str, str]:
    return await account(http, a, "bank"), await account(http, a, "sales", kind="income")


# --- import, matching, results, close ----------------------------------------------------------------------


async def test_import_match_results_and_close_with_an_integer_summary(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    bank, sales = await setup(http, a)
    await book(http, a, "t1", bank, sales, 10_000, "REF-1")
    await book(http, a, "t2", bank, sales, 2_500)
    await book(http, a, "t3", bank, sales, -4_000, "REF-3")
    await book(http, a, "t4", bank, sales, 777)  # on the books, not on the statement
    r = await import_run(
        http, a, "stmt-1", bank,
        [line("L1", 10_000, "REF-1"), line("L2", 2_500), line("L3", -4_000, "REF-3"), line("L4", 999)],
        name="March",
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "open" and run["line_count"] == 4 and run["matched_count"] == 0 and run["currency"] == "USD"
    assert set(run) == {"id", "account_id", "currency", "name", "period_start", "period_end", "status", "line_count", "matched_count", "created_at", "closed_at", "summary"}
    m = await http.post(f"/reconciliation/runs/{run['id']}/match", headers=a)
    assert m.status_code == 200 and m.json() == {"new_matches": 3, "matched_count": 3, "unmatched_line_count": 1}
    res = (await http.get(f"/reconciliation/runs/{run['id']}/results", headers=a)).json()
    assert {p["line"]["external_id"]: (p["match"]["method"], p["match"]["diff_minor"]) for p in res["matched"]} == {
        "L1": ("exact_reference", 0),
        "L2": ("exact", 0),
        "L3": ("exact_reference", 0),
    }
    assert [x["external_id"] for x in res["unmatched_lines"]] == ["L4"]
    assert [x["amount_minor"] for x in res["unmatched_entries"]] == [777] and res["entries_truncated"] is False
    s = res["summary"]
    assert s == {
        "currency": "USD", "line_count": 4, "matched_count": 3, "unmatched_line_count": 1, "unmatched_entry_count": 1,
        "statement_total_minor": 9_499, "matched_lines_minor": 8_500, "matched_entries_minor": 8_500, "matched_diff_minor": 0,
        "unmatched_lines_minor": 999, "unmatched_entries_minor": 777, "difference_minor": 222,
    }
    assert all(type(v) is int for k, v in s.items() if k != "currency")
    closed = await http.post(f"/reconciliation/runs/{run['id']}/close", headers=a)
    assert closed.status_code == 200 and closed.json()["status"] == "closed" and closed.json()["summary"] == s
    again = await http.post(f"/reconciliation/runs/{run['id']}/close", headers=a)
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true" and again.json()["summary"] == s
    for call in (
        http.post(f"/reconciliation/runs/{run['id']}/match", headers=a),
        http.post(f"/reconciliation/runs/{run['id']}/lines", json={"lines": [line("L9", 5)]}, headers=a),
    ):
        refused = await call
        assert refused.status_code == 409 and refused.json()["code"] == "run_closed"
    assert set(refused.json()) == {"code", "message", "details"}
    # the database freezes a closed run: lines and matches cannot be added, changed or removed behind the API
    for sql in (
        "insert into reconciliation_lines (tenant_id, run_id, line_no, external_id, line_date, amount, currency) "
        "select tenant_id, id, 99, 'X', '2026-03-01', 5, 'USD' from reconciliation_runs",
        "delete from reconciliation_matches",
        "update reconciliation_lines set amount = 1",
    ):
        with pytest.raises(sa.exc.DBAPIError, match="is closed"):
            async with engine.begin() as conn:
                await conn.execute(sa.text(sql))
    listed = (await http.get("/reconciliation/runs", params={"status": "closed"}, headers=a)).json()
    assert listed["total"] == 1 and (await http.get(f"/reconciliation/runs/{run['id']}", headers=a)).json()["summary"] == s


async def test_reference_wins_over_order_and_tolerance_pairs_close_amounts(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    bank, sales = await setup(http, a)
    first = await book(http, a, "t1", bank, sales, 1_000, "OTHER")  # posted first, same amount, other reference
    second = await book(http, a, "t2", bank, sales, 1_000, "WANTED")
    near = await book(http, a, "t3", bank, sales, 2_000)
    far = await book(http, a, "t4", bank, sales, 3_000)
    run = (await import_run(http, a, "s", bank, [line("A", 1_000, "WANTED"), line("B", 2_003), line("C", 3_010)])).json()
    assert (await http.post(f"/reconciliation/runs/{run['id']}/match", headers=a)).json()["new_matches"] == 2
    res = (await http.get(f"/reconciliation/runs/{run['id']}/results", headers=a)).json()
    by_line = {p["line"]["external_id"]: p for p in res["matched"]}
    assert by_line["A"]["entry"]["transaction_id"] == second["id"] and by_line["A"]["match"]["method"] == "exact_reference"
    assert by_line["B"]["entry"]["transaction_id"] == near["id"]
    assert (by_line["B"]["match"]["method"], by_line["B"]["match"]["diff_minor"]) == ("tolerance", 3)
    assert [x["external_id"] for x in res["unmatched_lines"]] == ["C"]  # 10 apart: outside the tolerance of 5
    assert {x["transaction_id"] for x in res["unmatched_entries"]} == {first["id"], far["id"]}
    assert res["summary"]["matched_diff_minor"] == 3 and res["summary"]["difference_minor"] == 3 + 3_010 - (1_000 + 3_000)


async def test_import_is_idempotent_and_validated(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    bank, sales = await setup(http, a)
    eur = await account(http, a, "bank-eur", "EUR")
    lines = [line("L1", 100), line("L2", 200)]
    first = await import_run(http, a, "same", bank, lines)
    assert first.status_code == 201
    replay = await import_run(http, a, "same", bank, lines)
    assert replay.status_code == 200 and replay.headers["Idempotent-Replayed"] == "true" and replay.json()["id"] == first.json()["id"]
    assert await scalar("select count(*) from reconciliation_runs") == 1 and await scalar("select count(*) from reconciliation_lines") == 2
    conflict = await import_run(http, a, "same", bank, [line("L1", 101)])
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"
    assert (await import_run(http, a, "dup", bank, [line("L1", 1), line("L1", 2)])).json()["code"] == "duplicate_line"
    assert (await import_run(http, a, "cur", bank, [line("L1", 1, cur="EUR")])).json()["code"] == "currency_mismatch"
    assert (await import_run(http, a, "zero", bank, [line("L1", 0)])).status_code == 422
    assert (await import_run(http, a, "float", bank, [line("L1", 10.5)])).status_code == 422  # type: ignore[list-item]
    assert (await import_run(http, a, "str", bank, [line("L1", "10")])).status_code == 422  # type: ignore[list-item]
    assert (await import_run(http, a, "none", bank, [])).status_code == 422
    ghost = "00000000-0000-0000-0000-000000000000"
    assert (await import_run(http, a, "ghost", ghost, lines)).json()["code"] == "unknown_account"
    assert (await import_run(http, a, "period", bank, lines, period_start="2026-03-10", period_end="2026-03-01")).json()["code"] == "invalid_period"
    assert (await import_run(http, a, "e", eur, [line("E1", 5, cur="EUR")])).status_code == 201  # another account, same call shape
    too_many = [line(f"M{n}", n + 1) for n in range(501)]
    assert (await import_run(http, a, "many", bank, too_many)).status_code == 422  # max_lines is 500
    # appending lines: known ids with the same content are skipped, other content is a conflict
    run_id = first.json()["id"]
    added = await http.post(f"/reconciliation/runs/{run_id}/lines", json={"lines": [line("L2", 200), line("L3", 300)]}, headers=a)
    assert added.json() == {"added": 1, "skipped": 1, "line_count": 3}
    clash = await http.post(f"/reconciliation/runs/{run_id}/lines", json={"lines": [line("L3", 301)]}, headers=a)
    assert clash.status_code == 409 and clash.json()["code"] == "line_conflict"
    assert await scalar("select count(*) from reconciliation_lines where run_id = :r", r=run_id) == 3


async def test_manual_match_unmatch_and_the_event_log(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    bank, sales = await setup(http, a)
    tx = await book(http, a, "t1", bank, sales, 5_000)
    entry = next(e["id"] for e in tx["entries"] if e["amount_minor"] == 5_000)
    run1 = (await import_run(http, a, "r1", bank, [line("L1", 5_050)])).json()
    run2 = (await import_run(http, a, "r2", bank, [line("L1", 5_000)])).json()
    line1 = (await http.get(f"/reconciliation/runs/{run1['id']}/results", headers=a)).json()["unmatched_lines"][0]["id"]
    line2 = (await http.get(f"/reconciliation/runs/{run2['id']}/results", headers=a)).json()["unmatched_lines"][0]["id"]
    made = await http.post(f"/reconciliation/runs/{run1['id']}/matches", json={"line_id": line1, "entry_id": entry}, headers=a)
    assert made.status_code == 201 and made.json()["method"] == "manual" and made.json()["diff_minor"] == 50
    # the entry is taken, in any run
    again = await http.post(f"/reconciliation/runs/{run2['id']}/matches", json={"line_id": line2, "entry_id": entry}, headers=a)
    assert again.status_code == 409 and again.json()["code"] == "entry_already_matched"
    assert (await http.post(f"/reconciliation/runs/{run2['id']}/match", headers=a)).json()["new_matches"] == 0  # auto-match skips it too
    # a line of another run, and an entry of another account, are not found
    assert (await http.post(f"/reconciliation/runs/{run2['id']}/matches", json={"line_id": line1, "entry_id": entry}, headers=a)).status_code == 404
    other = await account(http, a, "other")
    stray = await book(http, a, "t2", other, sales, 5)
    stray_entry = next(e["id"] for e in stray["entries"] if e["amount_minor"] == 5)
    assert (await http.post(f"/reconciliation/runs/{run2['id']}/matches", json={"line_id": line2, "entry_id": stray_entry}, headers=a)).status_code == 404
    # un-match frees the entry; the second run can now take it
    gone = await http.delete(f"/reconciliation/runs/{run1['id']}/matches/{made.json()['id']}", headers=a)
    assert gone.status_code == 200 and gone.json()["id"] == made.json()["id"]
    assert (await http.delete(f"/reconciliation/runs/{run1['id']}/matches/{made.json()['id']}", headers=a)).status_code == 404
    assert (await http.post(f"/reconciliation/runs/{run2['id']}/match", headers=a)).json()["new_matches"] == 1
    actions = (await scalar("select string_agg(action, ',' order by created_at, id) from reconciliation_events where run_id = :r", r=run1["id"]))
    assert str(actions).split(",") == ["import", "match", "unmatch"]
    with pytest.raises(sa.exc.DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(sa.text("update reconciliation_events set action = 'close'"))
    with pytest.raises(sa.exc.DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(sa.text("delete from reconciliation_events"))


async def test_eight_parallel_runs_and_matches_never_double_match(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    bank, sales = await setup(http, a)
    only = await book(http, a, "only", bank, sales, 1_234)
    entry = next(e["id"] for e in only["entries"] if e["amount_minor"] == 1_234)
    # 8 runs (one line of 1234 each) all auto-match at once: the single entry goes to exactly one of them
    runs = [(await import_run(http, a, f"par-{n}", bank, [line("L", 1_234)])).json() for n in range(8)]
    results = await asyncio.gather(*(http.post(f"/reconciliation/runs/{r['id']}/match", headers=a) for r in runs))
    assert [r.status_code for r in results] == [200] * 8
    assert sorted(r.json()["new_matches"] for r in results) == [0] * 7 + [1]
    assert await scalar("select count(*) from reconciliation_matches where entry_id = :e", e=entry) == 1
    # 8 parallel auto-matches of ONE run: no duplicates, every line matched once
    more = [await book(http, a, f"m{n}", bank, sales, 10 + n) for n in range(8)]
    big = (await import_run(http, a, "big", bank, [line(f"B{n}", 10 + n) for n in range(8)])).json()
    results = await asyncio.gather(*(http.post(f"/reconciliation/runs/{big['id']}/match", headers=a) for _ in range(8)))
    assert [r.status_code for r in results] == [200] * 8
    assert sum(r.json()["new_matches"] for r in results) == 8 and len(more) == 8
    assert await scalar("select count(*) from reconciliation_matches where run_id = :r", r=big["id"]) == 8
    # 8 parallel manual matches of the same pair: one wins, the rest are 409, nothing is double booked
    tx = await book(http, a, "manual", bank, sales, 99_999)
    e2 = next(e["id"] for e in tx["entries"] if e["amount_minor"] == 99_999)
    run = (await import_run(http, a, "man", bank, [line("M", 99_999)])).json()
    line_id = (await http.get(f"/reconciliation/runs/{run['id']}/results", headers=a)).json()["unmatched_lines"][0]["id"]
    tries = await asyncio.gather(
        *(http.post(f"/reconciliation/runs/{run['id']}/matches", json={"line_id": line_id, "entry_id": e2}, headers=a) for _ in range(8))
    )
    assert sorted(t.status_code for t in tries) == [201] + [409] * 7
    assert {t.json()["code"] for t in tries if t.status_code == 409} <= {"entry_already_matched", "line_already_matched"}
    assert await scalar("select count(*) from reconciliation_matches where entry_id = :e", e=e2) == 1
    # and the database refuses a second match of the same entry on its own
    with pytest.raises(sa.exc.IntegrityError, match="uq_reconciliation_matches_entry_id"):
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "insert into reconciliation_matches (tenant_id, run_id, line_id, entry_id, method, diff_minor) "
                    "select tenant_id, run_id, line_id, entry_id, 'manual', 0 from reconciliation_matches where entry_id = :e"
                ),
                {"e": e2},
            )
    dup_line = await scalar("select count(*) from (select line_id from reconciliation_matches group by line_id having count(*) > 1) d")
    dup_entry = await scalar("select count(*) from (select entry_id from reconciliation_matches group by entry_id having count(*) > 1) d")
    assert (dup_line, dup_entry) == (0, 0)


# --- isolation and roles -----------------------------------------------------------------------------------


async def test_tenants_are_isolated_and_roles_are_enforced(http, people) -> None:  # noqa: ANN001
    a, member, b, nobody = people["a"], people["a_member"], people["b"], people["nobody"]
    bank, sales = await setup(http, a)
    await book(http, a, "t1", bank, sales, 10)
    run = (await import_run(http, a, "r", bank, [line("L1", 10)])).json()
    assert (await http.get("/reconciliation/runs", headers=b)).json()["total"] == 0
    for method, path in (
        ("get", f"/reconciliation/runs/{run['id']}"),
        ("get", f"/reconciliation/runs/{run['id']}/results"),
        ("post", f"/reconciliation/runs/{run['id']}/match"),
        ("post", f"/reconciliation/runs/{run['id']}/close"),
    ):
        assert (await http.request(method, path, headers=b)).status_code == 404, path
    leak = await import_run(http, b, "leak", bank, [line("L1", 10)])
    assert leak.status_code == 422 and leak.json()["code"] == "unknown_account"
    assert (await http.get(f"/reconciliation/runs/{run['id']}", headers=member)).status_code == 200  # may read
    assert (await http.get(f"/reconciliation/runs/{run['id']}/results", headers=member)).status_code == 200
    assert (await http.post(f"/reconciliation/runs/{run['id']}/match", headers=member)).status_code == 403  # may not run
    assert (await import_run(http, member, "m", bank, [line("L1", 10)])).status_code == 403
    assert (await http.get("/reconciliation/runs", headers=nobody)).status_code == 403
    assert (await http.get("/reconciliation/runs")).status_code == 401
    assert (await import_run(http, {}, "anon", bank, [line("L1", 10)])).status_code == 401
    assert await scalar("select count(*) from reconciliation_runs") == 1
