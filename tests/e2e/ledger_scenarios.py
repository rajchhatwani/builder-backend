"""Scenario tests for the money pack in the generated `money_ledger` project (copied into the project's tests/
by tests/e2e/test_ledger_stack.py, run against a real Postgres).

Multi-tenant "Books" with packs.money.ledger (admin and member may read and post) and packs.money.currency
(EUR, JPY, KWD, USD). Proves: every transaction sums to zero per currency (also under 8 parallel posts), the
database itself refuses unbalanced, one-sided, edited and deleted rows (raw SQL, no API), balances equal
SUM(entries), idempotent posting, reversals, tenant isolation, roles, no 500.
"""

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import engine, session_factory
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
        "nobody": await sign_in(http, "nobody@example.com", roles=[], n=3, join="a@example.com"),
    }


async def account(http: AsyncClient, who: dict[str, str], code: str, cur: str = "USD", kind: str = "asset") -> str:
    r = await http.post("/ledger/accounts", json={"code": code, "name": code.title(), "kind": kind, "currency": cur}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def lines(*pairs: tuple[str, int]) -> list[dict[str, object]]:
    return [{"account_id": a, "amount_minor": n} for a, n in pairs]


async def post(http: AsyncClient, who: dict[str, str], key: str, entries: list[dict[str, object]], **extra: object):  # noqa: ANN201
    return await http.post("/ledger/transactions", json={"idempotency_key": key, "entries": entries, **extra}, headers=who)


async def scalar(sql: str, **params: object) -> object:
    async with session_factory() as session:
        return (await session.execute(sa.text(sql), params)).scalar_one()


async def assert_books_balance() -> None:
    """The invariants, straight from the tables: every transaction sums to zero per currency, the world sums to zero."""
    async with session_factory() as session:
        bad = (
            await session.execute(
                sa.text("select transaction_id, currency, sum(amount) from ledger_entries group by 1, 2 having sum(amount) <> 0")
            )
        ).all()
        assert bad == []
        assert (await session.execute(sa.text("select coalesce(sum(amount), 0) from ledger_entries"))).scalar_one() == 0
        lonely = (
            await session.execute(
                sa.text(
                    "select t.id from ledger_transactions t left join ledger_entries e on e.transaction_id = t.id "
                    "group by t.id having count(e.id) < 2"
                )
            )
        ).all()
        assert lonely == []


# --- the happy path and the contract -------------------------------------------------------------------------


async def test_post_balances_entries_and_contract_shapes(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    cash, sales = await account(http, a, "cash"), await account(http, a, "sales", kind="income")
    r = await post(http, a, "k1", lines((cash, 1250), (sales, -1250)), description="first sale", reference="INV-1")
    assert r.status_code == 201, r.text
    tx = r.json()
    assert set(tx) == {"id", "idempotency_key", "description", "reference", "reverses_id", "reversed_by_id", "posted_at", "posted_by", "entries"}
    assert tx["reverses_id"] is None and tx["reversed_by_id"] is None and tx["description"] == "first sale"
    assert [(e["line_no"], e["amount_minor"], e["direction"], e["currency"]) for e in tx["entries"]] == [
        (1, 1250, "debit", "USD"),
        (2, -1250, "credit", "USD"),
    ]
    bal = (await http.get("/ledger/balances", headers=a)).json()
    assert {i["code"]: (i["balance_minor"], i["debit_total_minor"], i["credit_total_minor"]) for i in bal["items"]} == {
        "cash": (1250, 1250, 0),
        "sales": (-1250, 0, -1250),
    }
    assert bal["totals"] == [{"currency": "USD", "sum_minor": 0}]
    accounts = (await http.get("/ledger/accounts", headers=a)).json()
    assert accounts["total"] == 2 and [i["code"] for i in accounts["items"]] == ["cash", "sales"]
    assert accounts["items"][0]["exponent"] == 2 and set(accounts) == {"items", "total", "limit", "offset"}
    history = (await http.get(f"/ledger/accounts/{cash}/entries", headers=a)).json()
    assert history["total"] == 1 and history["items"][0]["transaction_id"] == tx["id"] and history["items"][0]["description"] == "first sale"
    listed = (await http.get("/ledger/transactions", headers=a)).json()
    assert listed["total"] == 1 and listed["items"][0]["entries"][0]["amount_minor"] == 1250
    assert (await http.get(f"/ledger/transactions/{tx['id']}", headers=a)).json()["id"] == tx["id"]
    assert (await http.get("/ledger/transactions", params={"account_id": sales}, headers=a)).json()["total"] == 1
    dup = await http.post("/ledger/accounts", json={"code": "cash", "name": "x", "kind": "asset", "currency": "USD"}, headers=a)
    assert dup.status_code == 409 and dup.json()["code"] == "duplicate_account"
    bad = await http.post("/ledger/accounts", json={"code": "gbp", "name": "x", "kind": "asset", "currency": "GBP"}, headers=a)
    assert bad.status_code == 422 and bad.json()["code"] == "unsupported_currency"
    await assert_books_balance()


async def test_multi_currency_in_one_transaction_balances_per_currency(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    usd1, usd2 = await account(http, a, "usd1"), await account(http, a, "usd2")
    jpy1, jpy2 = await account(http, a, "jpy1", "JPY"), await account(http, a, "jpy2", "JPY")
    kwd1, kwd2 = await account(http, a, "kwd1", "KWD"), await account(http, a, "kwd2", "KWD")
    ok = await post(http, a, "multi", lines((usd1, 100), (usd2, -100), (jpy1, 5000), (jpy2, -5000), (kwd1, 1234), (kwd2, -1234)))
    assert ok.status_code == 201, ok.text
    assert {e["currency"] for e in ok.json()["entries"]} == {"USD", "JPY", "KWD"}
    # +100 USD and -100 JPY add to zero as numbers but not per currency: refused
    mixed = await post(http, a, "mixed", lines((usd1, 100), (jpy1, -100)))
    assert mixed.status_code == 422 and mixed.json()["code"] == "unbalanced"
    assert {d["currency"] for d in mixed.json()["details"]} == {"USD", "JPY"}
    assert money.exponent("KWD") == 3 and money.exponent("JPY") == 0 and money.exponent("USD") == 2
    await assert_books_balance()


async def test_bad_requests_are_refused_without_writing(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    x, y = await account(http, a, "x"), await account(http, a, "y")
    for amount in (10.0, "10", True, 1.5):  # strict integers only
        r = await post(http, a, "f", lines((x, amount), (y, -10)))  # type: ignore[arg-type]
        assert r.status_code == 422 and r.json()["code"] == "validation_error", (amount, r.text)
    assert (await post(http, a, "z", lines((x, 0), (y, 0)))).json()["code"] == "invalid_entries"
    assert (await post(http, a, "one", lines((x, 5)))).status_code == 422
    assert (await post(http, a, "huge", lines((x, 2**53), (y, -(2**53))))).status_code == 422
    unbalanced = await post(http, a, "u", lines((x, 100), (y, -99)))
    assert unbalanced.status_code == 422 and unbalanced.json()["details"] == [{"currency": "USD", "sum_minor": 1}]
    ghost = await post(http, a, "g", lines((x, 1), (str(uuid.uuid4()), -1)))
    assert ghost.status_code == 422 and ghost.json()["code"] == "unknown_account"
    assert await scalar("select count(*) from ledger_transactions") == 0
    assert await scalar("select count(*) from ledger_entries") == 0


# --- idempotency and reversal --------------------------------------------------------------------------------


async def test_idempotent_replay_and_conflict(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    x, y = await account(http, a, "x"), await account(http, a, "y")
    first = await post(http, a, "same", lines((x, 700), (y, -700)))
    again = await post(http, a, "same", lines((x, 700), (y, -700)))
    assert first.status_code == 201 and again.status_code == 200
    assert again.headers["idempotent-replayed"] == "true" and "idempotent-replayed" not in first.headers
    assert again.json()["id"] == first.json()["id"]
    other = await post(http, a, "same", lines((x, 800), (y, -800)))
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"
    assert await scalar("select count(*) from ledger_transactions") == 1
    # the key is per tenant: tenant B may use the same key
    b = people["b"]
    bx, by = await account(http, b, "x"), await account(http, b, "y")
    assert (await post(http, b, "same", lines((bx, 5), (by, -5)))).status_code == 201


async def test_reversal_corrects_by_a_new_transaction(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    x, y = await account(http, a, "x"), await account(http, a, "y")
    tx = (await post(http, a, "orig", lines((x, 500), (y, -500)))).json()
    rev = await http.post(f"/ledger/transactions/{tx['id']}/reverse", json={"idempotency_key": "rev1"}, headers=a)
    assert rev.status_code == 201, rev.text
    body = rev.json()
    assert body["reverses_id"] == tx["id"]
    assert [e["amount_minor"] for e in body["entries"]] == [-500, 500]
    assert (await http.get(f"/ledger/transactions/{tx['id']}", headers=a)).json()["reversed_by_id"] == body["id"]
    bal = (await http.get("/ledger/balances", headers=a)).json()
    assert [i["balance_minor"] for i in bal["items"]] == [0, 0]
    replay = await http.post(f"/ledger/transactions/{tx['id']}/reverse", json={"idempotency_key": "rev1"}, headers=a)
    assert replay.status_code == 200 and replay.json()["id"] == body["id"]
    twice = await http.post(f"/ledger/transactions/{tx['id']}/reverse", json={"idempotency_key": "rev2"}, headers=a)
    assert twice.status_code == 409 and twice.json()["code"] == "already_reversed"
    of_reversal = await http.post(f"/ledger/transactions/{body['id']}/reverse", json={"idempotency_key": "rev3"}, headers=a)
    assert of_reversal.status_code == 422 and of_reversal.json()["code"] == "cannot_reverse_reversal"
    missing = await http.post(f"/ledger/transactions/{uuid.uuid4()}/reverse", json={"idempotency_key": "rev4"}, headers=a)
    assert missing.status_code == 404
    assert await scalar("select count(*) from ledger_transactions") == 2
    await assert_books_balance()


# --- concurrency ---------------------------------------------------------------------------------------------


async def test_eight_parallel_posts_never_break_the_books(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    ids = [await account(http, a, f"acc{i}") for i in range(4)]
    jpy = [await account(http, a, f"jpy{i}", "JPY") for i in range(2)]

    def entries(n: int) -> list[dict[str, object]]:
        # every post touches the same accounts, in a different order each time
        order = ids[n % 4 :] + ids[: n % 4]
        pairs = [(order[0], 100 + n), (order[1], -(100 + n)), (order[2], 7), (order[3], -7)]
        if n % 2:
            pairs += [(jpy[0], 50), (jpy[1], -50)]
        return lines(*pairs)

    results = await asyncio.gather(*(post(http, a, f"par-{n}", entries(n)) for n in range(8)))
    assert [r.status_code for r in results] == [201] * 8, [r.text for r in results]
    assert await scalar("select count(*) from ledger_transactions") == 8

    # the same key from 8 callers at once: exactly one transaction, seven replays
    same = await asyncio.gather(*(post(http, a, "one-key", entries(0)) for _ in range(8)))
    assert sorted(r.status_code for r in same) == [200] * 7 + [201], [r.text for r in same]
    assert len({r.json()["id"] for r in same}) == 1
    assert await scalar("select count(*) from ledger_transactions where idempotency_key = 'one-key'") == 1

    # 8 reversals of one transaction at once: one wins, the others are told it is reversed
    target = same[0].json()["id"]
    revs = await asyncio.gather(
        *(http.post(f"/ledger/transactions/{target}/reverse", json={"idempotency_key": f"r{n}"}, headers=a) for n in range(8))
    )
    assert sorted(r.status_code for r in revs) == [201] + [409] * 7, [r.text for r in revs]
    assert {r.json()["code"] for r in revs if r.status_code == 409} == {"already_reversed"}

    # parallel reads while writing never 500
    mixed = await asyncio.gather(
        *(post(http, a, f"mix-{n}", entries(n)) for n in range(4)),
        *(http.get("/ledger/balances", headers=a) for _ in range(4)),
    )
    assert all(r.status_code in (200, 201) for r in mixed)

    await assert_books_balance()
    bal = (await http.get("/ledger/balances", headers=a)).json()
    async with session_factory() as session:
        raw = dict((await session.execute(sa.text("select account_id::text, sum(amount) from ledger_entries group by 1"))).all())
    for item in bal["items"]:
        assert item["balance_minor"] == int(raw.get(item["account_id"], 0)), item
        assert item["balance_minor"] == item["debit_total_minor"] + item["credit_total_minor"]
    assert all(t["sum_minor"] == 0 for t in bal["totals"])


# --- the database refuses, with no API in the way ------------------------------------------------------------


async def _raw_post(conn: AsyncConnection, tenant: uuid.UUID, rows: list[tuple[uuid.UUID, str, int]], tx: uuid.UUID | None = None) -> uuid.UUID:
    """Insert a header (a new transaction id) and its entries; with `tx` given, only entries for that header."""
    header = tx is None
    tx = tx or uuid.uuid4()
    if header:
        await conn.execute(
            sa.text("insert into ledger_transactions (id, tenant_id, idempotency_key, request_hash) values (:i, :t, :k, 'h')"),
            {"i": tx, "t": tenant, "k": f"raw-{tx}"},
        )
    for n, (acc, cur, amount) in enumerate(rows, start=1):
        await conn.execute(
            sa.text(
                "insert into ledger_entries (transaction_id, tenant_id, account_id, currency, amount, line_no) "
                "values (:tx, :t, :a, :c, :m, :n)"
            ),
            {"tx": tx, "t": tenant, "a": acc, "c": cur, "m": amount, "n": n},
        )
    return tx


async def test_the_database_itself_refuses_unbalanced_and_edited_rows(http, people) -> None:  # noqa: ANN001
    a, b = people["a"], people["b"]
    x, y = await account(http, a, "x"), await account(http, a, "y")
    eur = await account(http, a, "eur", "EUR")
    other = await account(http, b, "other")
    good = (await post(http, a, "good", lines((x, 300), (y, -300)))).json()
    async with session_factory() as s:
        tenant = (await s.execute(sa.text("select tenant_id from ledger_accounts where id = :i"), {"i": x})).scalar_one()
    xu, yu, eu, ou = (uuid.UUID(v) for v in (x, y, eur, other))

    async def refused(rows: list[tuple[uuid.UUID, str, int]], message: str, tenant_id: uuid.UUID = tenant) -> None:
        with pytest.raises(sa.exc.DBAPIError) as err:
            async with engine.begin() as conn:  # the commit runs the deferred constraint trigger
                await _raw_post(conn, tenant_id, rows)
        assert message in str(err.value)

    await refused([(xu, "USD", 100), (yu, "USD", -99)], "does not sum to zero")  # unbalanced
    await refused([(xu, "USD", 100)], "at least two entries")  # one-sided
    await refused([(xu, "USD", 100), (eu, "EUR", -100)], "does not sum to zero")  # sums to 0 as numbers, not per currency
    await refused([(xu, "EUR", 100), (yu, "EUR", -100)], "violates foreign key")  # entry currency != account currency
    await refused([(xu, "USD", 100), (ou, "USD", -100)], "mixes tenants")  # an account of another tenant
    with pytest.raises(sa.exc.DBAPIError, match="at least two entries"):  # a header with no entries at all
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("insert into ledger_transactions (tenant_id, idempotency_key, request_hash) values (:t, 'empty', 'h')"),
                {"t": tenant},
            )
    with pytest.raises(sa.exc.DBAPIError, match="violates check constraint"):  # zero amounts
        async with engine.begin() as conn:
            await _raw_post(conn, tenant, [(xu, "USD", 0), (yu, "USD", 0)])

    # a balanced pair appended to an OLD transaction is refused too
    with pytest.raises(sa.exc.DBAPIError, match="only be added in the transaction that created"):
        async with engine.begin() as conn:
            await _raw_post(conn, tenant, [(xu, "USD", 1), (yu, "USD", -1)], tx=uuid.UUID(good["id"]))

    # a balanced one commits (the guard is not a blanket refusal)
    async with engine.begin() as conn:
        await _raw_post(conn, tenant, [(xu, "USD", 40), (yu, "USD", -40)])

    # append-only: no UPDATE, no DELETE, on the entries or the transactions
    for sql in (
        "update ledger_entries set amount = amount + 1",
        "update ledger_entries set account_id = account_id",
        "delete from ledger_entries",
        "update ledger_transactions set description = 'edited'",
        "delete from ledger_transactions",
        "delete from ledger_accounts",
        "update ledger_accounts set currency = 'EUR' where code = 'x'",
        "update ledger_accounts set code = 'renamed' where code = 'x'",
    ):
        with pytest.raises(sa.exc.DBAPIError) as err:
            async with engine.begin() as conn:
                await conn.execute(sa.text(sql))
        assert "append-only" in str(err.value) or "cannot" in str(err.value), (sql, str(err.value))
    for table in ("ledger_entries", "ledger_transactions", "ledger_accounts"):  # TRUNCATE is refused too
        with pytest.raises(sa.exc.DBAPIError, match="TRUNCATE"):
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"truncate table {table} cascade"))
    async with engine.begin() as conn:  # an account may be renamed (its identity stays)
        await conn.execute(sa.text("update ledger_accounts set name = 'Renamed' where code = 'x'"))

    # nothing leaked from the refused attempts
    assert await scalar("select count(*) from ledger_transactions") == 2
    assert await scalar("select count(*) from ledger_entries") == 4
    await assert_books_balance()


async def test_balances_flags_a_truncated_list(http, people) -> None:  # noqa: ANN001
    a = people["a"]
    await account(http, a, "only")
    body = (await http.get("/ledger/balances", headers=a)).json()
    assert body["truncated"] is False and len(body["items"]) == 1


# --- isolation, roles, auth ----------------------------------------------------------------------------------


async def test_tenants_are_isolated(http, people) -> None:  # noqa: ANN001
    a, b = people["a"], people["b"]
    x, y = await account(http, a, "x"), await account(http, a, "y")
    tx = (await post(http, a, "k", lines((x, 10), (y, -10)))).json()
    assert (await http.get("/ledger/accounts", headers=b)).json()["total"] == 0
    assert (await http.get("/ledger/transactions", headers=b)).json()["total"] == 0
    assert (await http.get("/ledger/balances", headers=b)).json() == {"items": [], "totals": [], "truncated": False}
    assert (await http.get(f"/ledger/transactions/{tx['id']}", headers=b)).status_code == 404
    assert (await http.get(f"/ledger/accounts/{x}/entries", headers=b)).status_code == 404
    assert (await http.post(f"/ledger/transactions/{tx['id']}/reverse", json={"idempotency_key": "r"}, headers=b)).status_code == 404
    leak = await post(http, b, "leak", lines((x, 10), (y, -10)))
    assert leak.status_code == 422 and leak.json()["code"] == "unknown_account"
    assert await scalar("select count(*) from ledger_transactions") == 1


async def test_roles_and_sign_in_are_required(http, people) -> None:  # noqa: ANN001
    a, member, nobody = people["a"], people["a_member"], people["nobody"]
    x, y = await account(http, a, "x"), await account(http, a, "y")
    assert (await post(http, member, "m", lines((x, 3), (y, -3)))).status_code == 201  # member is a poster in this spec
    for method, path in (("get", "/ledger/accounts"), ("get", "/ledger/balances"), ("get", "/ledger/transactions")):
        assert (await http.request(method, path, headers=nobody)).status_code == 403
        assert (await http.request(method, path)).status_code == 401
    assert (await post(http, nobody, "n", lines((x, 3), (y, -3)))).status_code == 403
    assert (await http.post("/ledger/accounts", json={"code": "q", "name": "q", "kind": "asset", "currency": "USD"}, headers=nobody)).status_code == 403
    assert (await post(http, {}, "anon", lines((x, 3), (y, -3)))).status_code == 401
