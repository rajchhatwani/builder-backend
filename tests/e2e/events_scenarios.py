"""Scenario tests for the generated `events_orders` project. Copied into the project's tests/ folder by
tests/e2e/test_events_stack.py and run against a real Postgres, with real relay processes.

Rules under test: an event is delivered after the commit; a rolled-back write leaves no event; a committed
write keeps its event when the process dies right after the commit, and when the relay is down; a relay
killed with SIGKILL in the middle of a delivery loses nothing (the event is delivered again, in order);
two relays never deliver one event twice; events carry the tenant and no secret field.
"""

import asyncio
import importlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.auth.models import AuthUser
from app.crud.orders import OrderRepository
from app.db import session_factory
from app.events import bus
from app.events.models import DELIVERED, PENDING, OutboxEvent
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
async def http(outbox, tmp_path, monkeypatch) -> AsyncClient:  # noqa: ANN001, F811
    monkeypatch.setenv("EVENTS_SINK", str(tmp_path / "sink.jsonl"))
    monkeypatch.setenv("EVENTS_POLL_INTERVAL_SECONDS", "0.05")
    bus.clear_subscribers()
    import app.hooks.subscribers as subscribers

    importlib.reload(subscribers)  # the @subscribe lines run again
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def tenants(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "a": await sign_in(http, "a-admin@example.com", roles=["admin"], n=0),
        "b": await sign_in(http, "b-admin@example.com", roles=["admin"], n=1),
    }


def sink() -> list[dict]:
    path = Path(os.environ["EVENTS_SINK"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def rows() -> list[OutboxEvent]:
    async with session_factory() as session:
        stmt = sa.select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.seq)
        return list((await session.execute(stmt)).scalars())


async def wait_for(condition: Callable[[], object], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if (await result) if asyncio.iscoroutine(result) else result:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


def relay_env(**extra: str) -> dict[str, str]:
    return {**os.environ, "EVENTS_POLL_INTERVAL_SECONDS": "0.05", **extra}


def relay_once(**extra: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "app.events.relay", "--once"],
        cwd=ROOT, env=relay_env(**extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def finish(process: subprocess.Popen[str]) -> None:
    out, err = process.communicate(timeout=120)
    assert process.returncode == 0, out + err


async def place(http, who, ref="R1"):  # noqa: ANN001, ANN201
    response = await http.post("/orders", json={"reference": ref, "total": "10.00"}, headers=who)
    assert response.status_code == 201, response.text
    return response.json()


async def move(http, who, order, name):  # noqa: ANN001, ANN201
    response = await http.post(f"/orders/{order['id']}/transitions/{name}", headers=who)
    assert response.status_code == 200, response.text


def done(lines: list[dict]) -> list[dict]:
    return [line for line in lines if line["kind"] == "done"]


async def test_events_are_delivered_after_commit_in_order_with_tenant_and_no_secrets(http, tenants) -> None:  # noqa: ANN001
    who = tenants["a"]
    customer = await http.post(
        "/customers", json={"name": "Acme", "email": "a@acme.test", "api_token": "tok-SECRET-123"}, headers=who
    )
    assert customer.status_code == 201, customer.text
    order = await place(http, who)
    await move(http, who, order, "submit")
    await move(http, who, order, "approve")
    pending = await rows()
    assert [(r.event_type, r.seq) for r in pending if r.aggregate_id == uuid.UUID(order["id"])] == [
        ("order.created", 1), ("order.transitioned", 2), ("order.transitioned", 3),
    ]
    assert all(r.status == PENDING for r in pending)
    assert "tok-SECRET-123" not in json.dumps([r.payload for r in pending])
    async with session_factory() as session:
        tenant_a = (await session.execute(sa.select(AuthUser.tenant_id).where(AuthUser.email == "a-admin@example.com"))).scalar_one()
    assert {r.tenant_id for r in pending} == {tenant_a}

    async with app.router.lifespan_context(app):  # the app's own relay delivers
        await wait_for(lambda: len(done(sink())) == 4)
    delivered = done(sink())
    mine = [d for d in delivered if d["aggregate_id"] == order["id"]]
    assert [(d["seq"], d["type"]) for d in mine] == [(1, "order.created"), (2, "order.transitioned"), (3, "order.transitioned")]
    assert [(d["payload"]["from_state"], d["payload"]["to_state"]) for d in mine[1:]] == [
        ("draft", "submitted"), ("submitted", "approved"),
    ]
    assert all(d["tenant"] == str(tenant_a) == d["ctx_tenant"] for d in delivered)  # handlers run inside the tenant
    assert "tok-SECRET-123" not in Path(os.environ["EVENTS_SINK"]).read_text()
    assert all(r.status == DELIVERED for r in await rows())


async def test_a_rolled_back_write_leaves_no_event(http, tenants, monkeypatch) -> None:  # noqa: ANN001
    who = tenants["a"]
    order = await place(http, who)
    before = len(await rows())

    async def fail_late(ctx: object) -> None:
        raise RuntimeError("forced failure in after_save")

    hooks = {**OrderRepository.hooks, "after_save": (*OrderRepository.hooks.get("after_save", ()), fail_late)}
    monkeypatch.setattr(OrderRepository, "hooks", hooks)
    created = await http.post("/orders", json={"reference": "R2", "total": "5.00"}, headers=who)
    moved = await http.post(f"/orders/{order['id']}/transitions/submit", headers=who)
    assert created.status_code == 500 and moved.status_code == 500
    assert len(await rows()) == before  # neither the create nor the transition announced anything
    assert (await http.get(f"/orders/{order['id']}", headers=who)).json()["status"] == "draft"
    monkeypatch.undo()


async def test_a_committed_write_survives_a_dead_process_and_a_stopped_relay(http, tenants) -> None:  # noqa: ANN001
    who = tenants["a"]
    async with session_factory() as session:
        tenant_a = (await session.execute(sa.select(AuthUser.tenant_id).where(AuthUser.email == "a-admin@example.com"))).scalar_one()
    # A writer process commits and is killed with SIGKILL right after the commit: before any publish.
    script = (
        "import asyncio, os, signal, sys, uuid\n"
        "from app.crud.orders import OrderRepository\n"
        "from app.db import session_factory\n"
        "async def die(ctx):\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\n"
        "OrderRepository.hooks = {**OrderRepository.hooks, 'after_commit': (die,)}\n"
        "async def main():\n"
        "    async with session_factory() as s:\n"
        "        await OrderRepository(s, tenant_id=uuid.UUID(sys.argv[1])).create({'reference': 'CRASH', 'total': '1.00'})\n"
        "asyncio.run(main())\n"
    )
    crashed = subprocess.run([sys.executable, "-c", script, str(tenant_a)], cwd=ROOT, env=os.environ, capture_output=True, timeout=120)
    assert crashed.returncode == -9, crashed.stderr
    survivor = await rows()
    assert [(r.event_type, r.status) for r in survivor] == [("order.created", PENDING)]  # committed => event row exists
    # More writes while the relay is switched off (EVENTS_RELAY_ENABLED=false): nothing is published, nothing lost.
    first = await place(http, who, "R1")
    await move(http, who, first, "submit")
    os.environ["EVENTS_RELAY_ENABLED"] = "false"
    try:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.5)
            assert sink() == [] and all(r.status == PENDING for r in await rows())
    finally:
        os.environ.pop("EVENTS_RELAY_ENABLED", None)
    assert len(await rows()) == 3
    async with app.router.lifespan_context(app):  # the relay comes up and catches up, in order
        await wait_for(lambda: len(done(sink())) == 3)
    seen = done(sink())
    assert [d["type"] for d in seen if d["aggregate_id"] == first["id"]] == ["order.created", "order.transitioned"]
    assert all(r.status == DELIVERED for r in await rows())


async def test_a_relay_killed_with_sigkill_mid_delivery_loses_nothing(http, tenants) -> None:  # noqa: ANN001
    who = tenants["a"]
    order = await place(http, who)
    await move(http, who, order, "submit")
    hanging = subprocess.Popen(
        [sys.executable, "-m", "app.events.relay"], cwd=ROOT, env=relay_env(EVENTS_SINK_HANG="1"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        await wait_for(lambda: [line for line in sink() if line["kind"] == "start"])  # it is inside the handler now
        stuck = sink()[0]
        assert stuck["seq"] == 1
        hanging.kill()  # kill -9: the claim transaction is never committed
        hanging.wait(timeout=30)
    finally:
        if hanging.poll() is None:
            hanging.kill()
    mine = [r for r in await rows() if r.aggregate_id == uuid.UUID(order["id"])]
    assert [(r.seq, r.status, r.delivered_at) for r in mine] == [(1, PENDING, None), (2, PENDING, None)]
    finish(relay_once())  # a new relay claims the same row again (at least once) and carries on in order
    lines = sink()
    assert [line["id"] for line in lines if line["kind"] == "start"].count(stuck["id"]) == 2
    assert [(d["seq"]) for d in done(lines)] == [1, 2]
    assert all(r.status == DELIVERED for r in await rows())


async def test_two_relays_deliver_each_event_once_and_in_order(http, tenants) -> None:  # noqa: ANN001
    who = tenants["a"]
    orders = [await place(http, who, f"R{i}") for i in range(6)]
    await move(http, who, orders[0], "submit")
    await move(http, who, orders[0], "approve")
    total = len(await rows())
    relays = [relay_once(EVENTS_SINK_DELAY="0.3") for _ in range(2)]
    for relay in relays:
        finish(relay)
    lines = sink()
    starts = [line["id"] for line in lines if line["kind"] == "start"]
    assert len(starts) == len(set(starts)) == total  # no event was delivered twice
    # one event of a record is never in flight while another event of the same record runs
    for order in orders:
        mine = [line for line in lines if line["aggregate_id"] == order["id"]]
        assert [m["seq"] for m in mine if m["kind"] == "done"] == sorted(m["seq"] for m in mine if m["kind"] == "done")
    assert all(r.status == DELIVERED for r in await rows())


async def test_each_event_is_delivered_inside_its_own_tenant(http, tenants) -> None:  # noqa: ANN001
    made = {key: await place(http, who, key.upper()) for key, who in tenants.items()}
    async with session_factory() as session:
        owners = dict((await session.execute(sa.select(AuthUser.email, AuthUser.tenant_id))).all())
    finish(relay_once())
    delivered = {d["aggregate_id"]: d for d in done(sink())}
    for key, email in (("a", "a-admin@example.com"), ("b", "b-admin@example.com")):
        line = delivered[made[key]["id"]]
        assert line["tenant"] == line["ctx_tenant"] == str(owners[email])
    assert delivered[made["a"]["id"]]["tenant"] != delivered[made["b"]["id"]]["tenant"]


async def test_parallel_updates_of_one_record_get_distinct_gapless_sequence_numbers(http, tenants) -> None:  # noqa: ANN001
    who = tenants["a"]
    order = await place(http, who)
    answers = await asyncio.gather(
        *(http.patch(f"/orders/{order['id']}", json={"reference": f"P{i}"}, headers=who) for i in range(8))
    )
    assert {a.status_code for a in answers} == {200}, [a.text for a in answers]
    seqs = sorted(r.seq for r in await rows() if r.aggregate_id == uuid.UUID(order["id"]))
    assert seqs == list(range(1, 10))  # created + 8 updates, no duplicate, no gap


async def test_six_concurrent_deletes_of_one_order_write_exactly_one_deleted_event(http, tenants) -> None:  # noqa: ANN001
    who = tenants["a"]
    order = await place(http, who)
    answers = await asyncio.gather(*(http.delete(f"/orders/{order['id']}", headers=who) for _ in range(6)))
    assert sorted(a.status_code for a in answers) == [204, 404, 404, 404, 404, 404], [a.text for a in answers]
    mine = [r for r in await rows() if r.aggregate_id == uuid.UUID(order["id"])]
    assert [r.event_type for r in sorted(mine, key=lambda r: r.seq)][-1] == "order.deleted"
    assert len([r for r in mine if r.event_type == "order.deleted"]) == 1
    assert sorted(r.seq for r in mine) == list(range(1, len(mine) + 1))  # dense
