"""Scenario tests for the generated `realtime_metrics` project (copied into the project's tests/ by
tests/e2e/test_realtime_metrics_stack.py, run against a real Postgres and a real uvicorn server).

Expense: owner-scoped for staff (admin sees every row, role_scoped), soft delete, cost_basis readable by admin
only. Payroll: admin only. The metric results and the data they were computed from are dumped to the file
named by METRICS_DUMP so the platform test can recompute them with the builder's own metrics code.
"""

import asyncio
import json
import os
import socket
import time

import httpx
import pytest
import sqlalchemy as sa
import uvicorn
from httpx import ASGITransport, AsyncClient

from app.db import session_factory
from app.main import app
from app.realtime import protocol, router as rt_router
from tests._auth_support import outbox, sign_in  # noqa: F401

SECRET_CATEGORY = "SECRETCAT-" + "42"
SECRET_BASIS = "987654.321"


@pytest.fixture(autouse=True)
async def _fresh_state() -> None:
    rt_router.reset_state()
    async with session_factory() as session:
        await session.execute(sa.text("TRUNCATE TABLE rt_events, rt_floor"))
        await session.commit()


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "s1": await sign_in(http, "s1@example.com", roles=["staff"], n=0),
        "s2": await sign_in(http, "s2@example.com", roles=["staff"], n=1),
        "s3": await sign_in(http, "s3@example.com", roles=["staff"], n=2),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=3),
    }


@pytest.fixture
async def server():  # noqa: ANN201
    """The real app on a real socket (httpx's ASGI transport buffers a whole response, so it cannot stream)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    await task


class Stream:
    """One SSE client: collects frames in the background."""

    def __init__(self, base: str, headers: dict[str, str], *, last_event_id: str | None = None, query: str = "") -> None:
        self.headers = dict(headers)
        if last_event_id is not None:
            self.headers["Last-Event-ID"] = last_event_id
        self.url = f"{base}/realtime/stream{query}"
        self.events: list[dict] = []
        self.raw = ""
        self.opened = asyncio.Event()
        self.status = 0
        self._changed = asyncio.Event()

    async def start(self) -> "Stream":
        self._client = httpx.AsyncClient(timeout=None)
        self._cm = self._client.stream("GET", self.url, headers=self.headers)
        self._resp = await self._cm.__aenter__()
        self.status = self._resp.status_code
        if self.status != 200:
            self.raw = (await self._resp.aread()).decode()
            self.opened.set()
            return self
        self._task = asyncio.create_task(self._pump())
        await asyncio.wait_for(self.opened.wait(), 5)
        return self

    async def _pump(self) -> None:
        frame: list[str] = []
        try:
            async for line in self._resp.aiter_lines():
                self.raw += line + "\n"
                if line == "":
                    self._frame(frame)
                    frame = []
                else:
                    frame.append(line)
        except (httpx.HTTPError, asyncio.CancelledError):
            pass

    def _frame(self, lines: list[str]) -> None:
        if lines and lines[0].startswith(": open"):
            self.opened.set()
            return
        data = [ln[6:] for ln in lines if ln.startswith("data: ")]
        if not data:
            return
        event = json.loads(data[0])
        event["_sse_id"] = next((ln[4:] for ln in lines if ln.startswith("id: ")), None)
        self.events.append(event)
        self._changed.set()

    async def wait_for(self, count: int, timeout: float = 4.0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while len(self.events) < count and time.monotonic() < deadline:
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                break
        return self.events

    async def close(self) -> None:
        if self.status == 200:
            self._task.cancel()
        await self._cm.__aexit__(None, None, None)
        await self._client.aclose()


@pytest.fixture
async def streams():  # noqa: ANN201
    opened: list[Stream] = []

    async def open_stream(base: str, who: dict[str, str], **kwargs) -> Stream:  # noqa: ANN003
        stream = await Stream(base, who, **kwargs).start()
        opened.append(stream)
        return stream

    yield open_stream
    for stream in opened:
        await stream.close()


async def make(http: AsyncClient, who: dict[str, str], category: str = "food", amount: str = "10", **extra: object) -> str:
    response = await http.post("/expenses", json={"category": category, "amount": amount, **extra}, headers=who)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_a_write_by_one_person_reaches_another_within_two_seconds(http, people, server, streams) -> None:  # noqa: ANN001
    admin = await streams(server, people["admin"])
    mine = await streams(server, people["s1"])
    started = time.monotonic()
    expense = await make(http, people["s1"])
    assert len(await admin.wait_for(1, 2.0)) == 1 and time.monotonic() - started < 2.5
    event = admin.events[0]
    assert event["type"] == "Expense.created" and event["topic"] == "Expense"
    assert event["data"] == {"entity": "Expense", "record_id": expense, "op": "created"}
    assert event["_sse_id"] == str(event["id"])
    assert len(await mine.wait_for(1, 2.0)) == 1  # the owner sees their own change too
    patched = await http.patch(f"/expenses/{expense}", json={"qty": 3}, headers=people["s1"])
    assert patched.status_code == 200
    deleted = await http.delete(f"/expenses/{expense}", headers=people["s1"])
    assert deleted.status_code == 204
    await admin.wait_for(3)
    assert [e["data"]["op"] for e in admin.events] == ["created", "updated", "deleted"]
    ids = [e["id"] for e in admin.events]
    assert ids == sorted(ids) and len(set(ids)) == 3


async def test_reconnect_with_last_event_id_replays_exactly_the_missed_events(http, people, server, streams) -> None:  # noqa: ANN001
    admin = await streams(server, people["admin"])
    first = await make(http, people["s1"])
    await admin.wait_for(1)
    seen = admin.events[0]["id"]
    await admin.close()
    second = await make(http, people["s1"], "travel")
    patched = await http.patch(f"/expenses/{second}", json={"qty": 9}, headers=people["s1"])
    assert patched.status_code == 200
    third = await make(http, people["s2"], "misc")
    back = await streams(server, people["admin"], last_event_id=str(seen))
    await back.wait_for(3)
    await asyncio.sleep(1.2)  # a duplicate or an extra event would show up by now
    assert [(e["data"]["record_id"], e["data"]["op"]) for e in back.events] == [
        (second, "created"),
        (second, "updated"),
        (third, "created"),
    ]
    assert all(e["id"] > seen for e in back.events) and first not in {e["data"]["record_id"] for e in back.events}
    # the same cursor in the query string, and a live write after the replay arrives once
    again = await streams(server, people["admin"], query=f"?last_event_id={back.events[-1]['id']}")
    live = await make(http, people["s2"], "misc")
    await again.wait_for(1)
    await asyncio.sleep(0.8)
    assert [e["data"]["record_id"] for e in again.events] == [live]


async def test_a_cursor_that_cannot_be_replayed_gets_a_resync(http, people, server, streams) -> None:  # noqa: ANN001
    await make(http, people["s1"])
    ahead = await streams(server, people["admin"], last_event_id="999999999")
    await ahead.wait_for(1)
    assert ahead.events[0]["type"] == "resync" and ahead.events[0]["data"] == {"reason": "cursor_unavailable"}
    async with session_factory() as session:
        await session.execute(sa.text("INSERT INTO rt_floor (id, floor_id) VALUES (1, 500)"))
        await session.commit()
    stale = await streams(server, people["admin"], last_event_id="3")
    await stale.wait_for(1)
    assert stale.events[0]["type"] == "resync" and stale.events[0]["id"] == 500
    garbage = await streams(server, people["admin"], last_event_id="abc")  # garbage = no cursor
    await asyncio.sleep(0.3)
    assert garbage.status == 200 and garbage.events == []


async def test_people_receive_only_events_they_may_list(http, people, server, streams) -> None:  # noqa: ANN001
    admin = await streams(server, people["admin"])
    s1 = await streams(server, people["s1"])
    s2 = await streams(server, people["s2"])
    payroll = await http.post("/payrolls", json={"person": "Ann", "salary": "1000"}, headers=people["admin"])
    assert payroll.status_code == 201
    expense = await make(http, people["s1"])
    await admin.wait_for(2)
    await s1.wait_for(1)
    await asyncio.sleep(1.2)
    assert [e["type"] for e in admin.events] == ["Payroll.created", "Expense.created"]
    assert [e["type"] for e in s1.events] == ["Expense.created"]  # no role to list Payroll: nothing
    assert s2.events == []  # owner scope: another person's expense is not announced
    own = await make(http, people["s2"], "misc")
    await s2.wait_for(1)
    await asyncio.sleep(0.8)
    assert [e["data"]["record_id"] for e in s2.events] == [own]
    assert [e["data"]["record_id"] for e in s1.events] == [expense]
    # hard facts about the log: ids only
    async with session_factory() as session:
        rows = (await session.execute(sa.text("SELECT * FROM rt_events"))).mappings().all()
    assert {k for r in rows for k in r} == {"id", "entity", "record_id", "op", "tenant_id", "created_by_id", "created_at"}


async def test_events_never_carry_field_values(http, people, server, streams) -> None:  # noqa: ANN001
    admin = await streams(server, people["admin"])
    await make(http, people["admin"], SECRET_CATEGORY, "123.45", cost_basis=SECRET_BASIS)
    await admin.wait_for(1)
    assert admin.events[0]["data"].keys() == {"entity", "record_id", "op"}
    assert SECRET_CATEGORY not in admin.raw and SECRET_BASIS not in admin.raw and "123.45" not in admin.raw
    async with session_factory() as session:
        dump = str((await session.execute(sa.text("SELECT * FROM rt_events"))).all())
    assert SECRET_CATEGORY not in dump and SECRET_BASIS not in dump and "123.45" not in dump


async def test_concurrent_writes_arrive_in_order_without_gaps_or_duplicates(http, people, server, streams) -> None:  # noqa: ANN001
    admin = await streams(server, people["admin"])
    await asyncio.gather(*(make(http, people["s1"], amount=str(i + 1)) for i in range(15)))
    await admin.wait_for(15, 8.0)
    await asyncio.sleep(1.0)
    ids = [e["id"] for e in admin.events]
    assert len(ids) == 15 and ids == sorted(ids) and len(set(ids)) == 15


async def test_stream_needs_a_signed_in_person_and_is_limited(http, people, server, streams, monkeypatch) -> None:  # noqa: ANN001
    assert (await http.get("/realtime/stream")).status_code == 401
    held = [await streams(server, people["s3"]) for _ in range(protocol.MAX_STREAMS_PER_USER)]
    sixth = await Stream(server, people["s3"]).start()
    assert sixth.status == 429 and "realtime_too_many_streams" in sixth.raw
    await sixth.close()
    assert len(held) == protocol.MAX_STREAMS_PER_USER
    monkeypatch.setattr(rt_router, "_reconnects", protocol.ReconnectGuard(max_hits=2))
    ok_one = await streams(server, people["s2"])
    ok_two = await streams(server, people["s2"])
    assert ok_one.status == ok_two.status == 200
    third = await Stream(server, people["s2"]).start()
    assert third.status == 429 and "realtime_reconnect_throttled" in third.raw
    await third.close()


async def test_a_state_transition_is_announced_as_an_update(http, people, server, streams) -> None:  # noqa: ANN001
    expense = await make(http, people["s1"])
    admin = await streams(server, people["admin"])
    mine = await streams(server, people["s1"])
    other = await streams(server, people["s2"])  # owner scope: not their row
    moved = await http.post(f"/expenses/{expense}/transitions/approve", headers=people["s1"])
    assert moved.status_code == 200 and moved.json()["status"] == "approved"
    await admin.wait_for(1)
    await mine.wait_for(1)
    await asyncio.sleep(1.0)
    for stream in (admin, mine):
        assert [(e["type"], e["data"]) for e in stream.events] == [
            ("Expense.updated", {"entity": "Expense", "record_id": expense, "op": "updated"})
        ]
    assert other.events == []
    assert "approved" not in admin.raw  # ids only, never the new state


async def test_streams_have_a_global_cap_and_do_not_hold_a_pool_connection(http, people, server, streams, monkeypatch) -> None:  # noqa: ANN001
    from app.db import engine

    monkeypatch.setattr(rt_router, "_limiter", protocol.ConnectionLimiter(max_per_user=5, max_total=3))
    held = [
        await streams(server, people["s1"]),
        await streams(server, people["s2"]),
        await streams(server, people["admin"]),
    ]
    assert all(s.status == 200 for s in held)
    refused = await Stream(server, people["s3"]).start()
    assert refused.status == 503 and "realtime_at_capacity" in refused.raw
    await refused.close()
    await asyncio.sleep(1.2)  # polling is going on, with the idle backoff
    assert engine.pool.checkedout() == 0  # no stream keeps a database connection while it sleeps
    await held[0].close()
    again = await streams(server, people["s3"])  # a freed slot is usable again
    assert again.status == 200


# --- metrics ---------------------------------------------------------------------------------


@pytest.fixture
async def world(http, people):  # noqa: ANN001
    when = {"spent_on": "2024-03-01", "logged_at": "2024-03-01T10:00:00Z"}
    await make(http, people["s1"], "food", "10.10", qty=2, rate=0.1, paid=True, code="7", **when)
    await make(http, people["s1"], "food", "20.25", qty=3, rate=0.2, paid=False, code="7.0", **when)
    await make(http, people["s1"], "travel", "3.333", rate=0.3, code="abc", spent_on="2024-03-02")
    await make(http, people["s2"], "misc", "100.5", qty=1, rate=1.5, paid=True, code="abc")
    await make(http, people["admin"], "food", "5.5", qty=4, rate=0.7, paid=True, cost_basis="4.2")
    gone = await make(http, people["s1"], "food", "999")
    assert (await http.delete(f"/expenses/{gone}", headers=people["s1"])).status_code == 204
    for person, salary in (("Ann", "1000.50"), ("Bob", "2000.25")):
        assert (await http.post("/payrolls", json={"person": person, "salary": salary}, headers=people["admin"])).status_code == 201


async def rows(http: AsyncClient, who: dict[str, str], path: str) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        page = (await http.get(path, params={"limit": 100, "offset": offset}, headers=who)).json()
        out.extend({k: v for k, v in item.items() if k not in ("id", "created_at", "updated_at")} for item in page["items"])
        offset += 100
        if offset >= page["total"]:
            return out


async def metric(http: AsyncClient, who: dict[str, str], key: str) -> httpx.Response:
    return await http.get(f"/metrics/{key}", headers=who)


async def test_metrics_values_scope_and_refusals(http, people, world) -> None:  # noqa: ANN001
    admin = people["admin"]
    total = (await metric(http, admin, "expense_total")).json()
    assert total == {"key": "expense_total", "label": "Total expenses", "unit": "USD", "value": "139.683"}
    assert (await metric(http, admin, "expense_average")).json()["value"] == "27.9366"
    assert (await metric(http, admin, "expense_count")).json()["value"] == 5  # the soft-deleted one is not counted
    by_category = (await metric(http, admin, "expense_by_category")).json()
    assert by_category["groups"] == [
        {"key": "food", "value": "35.85"},
        {"key": "misc", "value": "100.5"},
        {"key": "travel", "value": "3.333"},
    ]
    by_paid = (await metric(http, admin, "expense_by_paid")).json()
    assert by_paid["groups"] == [{"key": "false", "value": 1}, {"key": "true", "value": 3}, {"key": None, "value": 1}]  # null group last
    assert (await metric(http, admin, "big_expense_max")).json()["value"] == "100.5"
    assert (await metric(http, admin, "categories_used")).json()["value"] == 3
    # count_distinct on text follows the builder: "7" and "7.0" are one number, "abc" another
    assert (await metric(http, admin, "codes_used")).json()["value"] == 2
    assert (await metric(http, admin, "codes_by_category")).json()["groups"] == [
        {"key": "food", "value": 1},
        {"key": "misc", "value": 1},
        {"key": "travel", "value": 1},
    ]
    # date and datetime group keys: the text the API prints, null group last
    assert (await metric(http, admin, "expense_by_day")).json()["groups"] == [
        {"key": "2024-03-01", "value": "30.35"},
        {"key": "2024-03-02", "value": "3.333"},
        {"key": None, "value": "106"},
    ]
    assert (await metric(http, admin, "expense_by_logged")).json()["groups"] == [
        {"key": "2024-03-01T10:00:00Z", "value": 2},
        {"key": None, "value": 3},
    ]
    assert (await metric(http, admin, "rate_total")).json()["value"] == "2.8"  # floats are read as their text form
    assert (await metric(http, admin, "cost_basis_total")).json()["value"] == "4.2"
    assert (await metric(http, admin, "payroll_total")).json()["value"] == "3000.75"
    # owner scope: a staff member aggregates only their own rows
    s1 = (await metric(http, people["s1"], "expense_total")).json()
    assert s1["value"] == "33.683" and (await metric(http, people["s1"], "expense_count")).json()["value"] == 3
    assert (await metric(http, people["s2"], "expense_total")).json()["value"] == "100.5"
    # a field the caller may not read, or an entity they may not list: refused, not zero
    hidden = await metric(http, people["s1"], "cost_basis_total")
    assert hidden.status_code == 403
    assert (await metric(http, people["s1"], "payroll_total")).status_code == 403
    assert (await metric(http, people["s1"], "nope")).status_code == 404
    assert (await http.get("/metrics/expense_total")).status_code == 401
    keys_s1 = {m["key"] for m in (await http.get("/metrics", headers=people["s1"])).json()}
    assert "expense_total" in keys_s1 and not keys_s1 & {"cost_basis_total", "payroll_total"}
    keys_admin = {m["key"] for m in (await http.get("/metrics", headers=admin)).json()}
    assert {"cost_basis_total", "payroll_total", "expense_total"} <= keys_admin
    # empty set (a person with no rows)
    s3 = people["s3"]
    assert (await metric(http, s3, "expense_total")).json()["value"] == "0"
    assert (await metric(http, s3, "expense_count")).json()["value"] == 0
    assert (await metric(http, s3, "codes_used")).json()["value"] == 0
    assert (await metric(http, s3, "expense_average")).json()["value"] is None
    assert (await metric(http, s3, "big_expense_max")).json()["value"] is None
    assert (await metric(http, s3, "expense_by_category")).json() == {
        "key": "expense_by_category", "label": "Expenses by category", "unit": None, "value": "0", "groups": []
    }


async def test_dump_for_the_platform_comparison(http, people, world) -> None:  # noqa: ANN001
    """The data each person can list and every metric they get, for tests/e2e/test_realtime_metrics_stack.py to
    recompute with the builder's own `compute()`."""
    dump: dict[str, dict] = {}
    for who in ("admin", "s1", "s2", "s3"):
        keys = [m["key"] for m in (await http.get("/metrics", headers=people[who])).json()]
        dump[who] = {
            "expenses": await rows(http, people[who], "/expenses"),
            "payrolls": await rows(http, people[who], "/payrolls") if who == "admin" else [],
            "results": {k: (await metric(http, people[who], k)).json() for k in keys},
        }
    with open(os.environ["METRICS_DUMP"], "w", encoding="utf-8") as handle:
        json.dump(dump, handle)
