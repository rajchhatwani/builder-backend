"""Event checks (generated): the outbox is written with the change, the relay delivers at least once and in order."""

import asyncio
import datetime as dt
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from structlog.testing import capture_logs

from app.core import redact
from app.crud.customers import CustomerRepository
from app.db import session_factory
from app.events import adapters, bus, config, definitions, outbox, relay
from app.events.models import DELIVERED, FAILED, PENDING, OutboxEvent
from app.events.types import EVENT_TYPES
from tests import _factories


@pytest.fixture(autouse=True)
def _own_subscribers() -> Iterator[None]:
    """Each test starts with no subscribers; the project's own are put back afterwards."""
    saved = {event: dict(handlers) for event, handlers in bus._SUBSCRIBERS.items()}
    bus.clear_subscribers()
    yield
    bus.clear_subscribers()
    bus._SUBSCRIBERS.update(saved)


class Recorder:
    """An adapter that records deliveries; `fail` decides which events it refuses."""

    name = "recorder"

    def __init__(
        self, fail: Callable[[bus.Event], bool] | None = None, delay: float = 0.0
    ) -> None:
        self.fail = fail or (lambda _event: False)
        self.delay = delay
        self.started: list[uuid.UUID] = []
        self.delivered: list[tuple[uuid.UUID, int, str]] = []
        self.active: set[uuid.UUID] = set()
        self.overlap = False

    async def publish(self, event: bus.Event) -> None:
        if event.id in self.active:
            self.overlap = True
        self.active.add(event.id)
        self.started.append(event.id)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail(event):
                raise RuntimeError("password=hunter2")
            self.delivered.append((event.aggregate_id, event.seq, event.type))
        finally:
            self.active.discard(event.id)

    async def close(self) -> None:
        return None


async def _all() -> list[OutboxEvent]:
    async with session_factory() as session:
        stmt = sa.select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.seq)
        return list((await session.execute(stmt)).scalars())


async def _make_due() -> None:
    """Pretend the backoff has passed for every pending event."""
    async with session_factory() as session:
        past = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        await session.execute(
            sa.update(OutboxEvent).where(OutboxEvent.status == PENDING).values(next_attempt_at=past)
        )
        await session.commit()


# --- the definitions ---------------------------------------------------------------------------


def test_every_entity_has_its_typed_events() -> None:
    assert definitions.ADAPTER == "in_process"
    for entity, cfg in definitions.ENTITIES.items():
        for kind in ("created", "updated", "deleted"):
            assert f"{cfg['event']}.{kind}" in EVENT_TYPES, (entity, kind)
        assert (f"{cfg['event']}.transitioned" in EVENT_TYPES) == cfg["machine"], entity


def test_events_never_carry_secret_looking_fields() -> None:
    for entity, cfg in definitions.ENTITIES.items():
        for name in cfg["fields"]:
            assert not redact.is_secret_key(name), (entity, name)
        data_fields = EVENT_TYPES[f"{cfg['event']}.created"].model_fields["data"].annotation
        assert data_fields is not None
        assert set(data_fields.model_fields) == set(cfg["fields"]), entity  # type: ignore[attr-defined]


def test_subscribing_to_an_unknown_event_is_refused() -> None:
    async def handler(event: bus.Event) -> None: ...

    with pytest.raises(ValueError, match="unknown event"):
        bus.subscribe("nothing.happened")(handler)


def test_the_redis_streams_adapter_is_a_stub() -> None:
    with pytest.raises(NotImplementedError, match="not implemented"):
        adapters.make_adapter("redis_streams")
    assert isinstance(adapters.make_adapter("in_process"), adapters.InProcessAdapter)


def test_retry_delay_doubles_up_to_a_cap() -> None:
    delays = [relay.backoff_seconds(n) for n in range(1, 12)]
    assert delays[0] == config.BACKOFF_BASE_SECONDS
    assert delays[1] == 2 * delays[0]
    assert max(delays) == config.BACKOFF_CAP_SECONDS


def test_a_bad_setting_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENTS_MAX_ATTEMPTS", "many")
    with pytest.raises(ValueError, match="EVENTS_MAX_ATTEMPTS"):
        config.max_attempts()
    monkeypatch.setenv("EVENTS_RELAY_ENABLED", "maybe")
    with pytest.raises(ValueError, match="EVENTS_RELAY_ENABLED"):
        config.relay_enabled()
    monkeypatch.delenv("EVENTS_RETENTION_DAYS", raising=False)
    assert config.retention_days() == definitions.RETENTION_DAYS


async def test_the_idempotency_helper_remembers_per_consumer_and_per_transaction() -> None:
    event_id = uuid.uuid4()
    async with session_factory() as session:
        assert await outbox.already_handled(session, event_id, "a") is False
        assert await outbox.already_handled(session, event_id, "a") is True
        assert await outbox.already_handled(session, event_id, "b") is False
        await session.rollback()  # the handler's work failed: nothing is remembered
    async with session_factory() as session:
        assert await outbox.already_handled(session, event_id, "a") is False
        await session.commit()
    async with session_factory() as session:
        assert await outbox.already_handled(session, event_id, "a") is True


# --- the outbox is written with the change ------------------------------------------------------

ENTITY = "Customer"
PREFIX = "customer"
PATH = "/customers"
FIELD = "name"
Repo = CustomerRepository


@pytest.fixture
def http(authed_client: AsyncClient) -> AsyncClient:
    return authed_client

async def _create(http: AsyncClient) -> dict[str, object]:
    return await _factories.make_customers(http)


async def _change(http: AsyncClient, record: dict[str, object]) -> None:
    for _ in range(100):
        value = _factories.sample_customers()[FIELD]
        if value != record[FIELD]:
            break
    else:
        pytest.fail("could not find a different value to patch")
    response = await http.patch(f"{PATH}/{record['id']}", json={FIELD: value})
    assert response.status_code == 200, response.text
    record[FIELD] = response.json()[FIELD]


async def test_a_create_writes_its_event_in_the_same_transaction(http: AsyncClient) -> None:
    record = await _create(http)
    (row,) = await _all()
    assert (row.event_type, row.aggregate_type, row.seq) == (f"{PREFIX}.created", ENTITY, 1)
    assert row.aggregate_id == uuid.UUID(record["id"])
    assert (row.status, row.attempts, row.delivered_at) == (PENDING, 0, None)
    assert row.payload["data"]["id"] == record["id"]
    assert set(row.payload["data"]) == set(definitions.ENTITIES[ENTITY]["fields"])
    assert row.tenant_id is not None


async def test_updates_and_deletes_follow_in_order_and_a_no_op_update_says_nothing(
    http: AsyncClient,
) -> None:
    record = await _create(http)
    await _change(http, record)
    same = await http.patch(f"{PATH}/{record['id']}", json={FIELD: record[FIELD]})
    assert same.status_code == 200
    assert (await http.delete(f"{PATH}/{record['id']}")).status_code == 204
    rows = await _all()
    assert [(r.seq, r.event_type) for r in rows] == [
        (1, f"{PREFIX}.created"),
        (2, f"{PREFIX}.updated"),
        (3, f"{PREFIX}.deleted"),
    ]
    assert rows[1].payload["changed"] == [FIELD]


async def test_concurrent_deletes_of_one_record_write_exactly_one_deleted_event(http: AsyncClient) -> None:
    record = await _create(http)
    answers = await asyncio.gather(*(http.delete(f"{PATH}/{record['id']}") for _ in range(6)))
    codes = sorted(a.status_code for a in answers)
    assert codes == [204, 404, 404, 404, 404, 404], codes  # one winner, the rest find nothing to delete
    deleted = [r for r in await _all() if r.event_type == f"{PREFIX}.deleted"]
    assert len(deleted) == 1
    assert sorted(r.seq for r in await _all()) == [1, 2]  # created, deleted: no gap, no duplicate


async def test_a_rolled_back_write_leaves_no_event(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_late(_ctx: object) -> None:
        raise RuntimeError("forced failure after the event was written")

    hooks = {**Repo.hooks, "after_save": (*Repo.hooks.get("after_save", ()), fail_late)}
    monkeypatch.setattr(Repo, "hooks", hooks)
    response = await http.post(PATH, json=await _factories.payload_customers(http))
    assert response.status_code == 500
    assert await _all() == []
    async with session_factory() as session:
        count = (await session.execute(sa.text("SELECT count(*) FROM customers"))).scalar_one()
    assert count == 0


async def test_an_event_that_cannot_be_written_rolls_the_write_back(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_args: object, **_kwargs: object) -> uuid.UUID:
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(outbox, "add_event", broken)
    response = await http.post(PATH, json=await _factories.payload_customers(http))
    assert response.status_code == 500
    async with session_factory() as session:
        count = (await session.execute(sa.text("SELECT count(*) FROM customers"))).scalar_one()
    assert count == 0


# --- the relay ----------------------------------------------------------------------------------


async def test_the_relay_delivers_once_and_in_order_per_record(http: AsyncClient) -> None:
    a = await _create(http)
    b = await _create(http)
    await _change(http, a)
    await _change(http, a)
    recorder = Recorder()
    delivered = await relay.deliver_batch(session_factory, recorder)
    assert delivered == 4
    for record in (a, b):
        seqs = [s for agg, s, _ in recorder.delivered if str(agg) == record["id"]]
        assert seqs == sorted(seqs) and seqs[0] == 1
    assert [s for agg, s, _ in recorder.delivered if str(agg) == a["id"]] == [1, 2, 3]
    assert all(r.status == DELIVERED and r.delivered_at is not None for r in await _all())
    assert await relay.deliver_batch(session_factory, recorder) == 0  # nothing is delivered twice


async def test_a_failing_event_holds_back_only_its_own_record_and_is_retried(
    http: AsyncClient,
) -> None:
    a = await _create(http)
    b = await _create(http)
    await _change(http, a)
    recorder = Recorder(fail=lambda e: str(e.aggregate_id) == a["id"] and e.seq == 1)
    await relay.deliver_batch(session_factory, recorder)
    assert [str(agg) for agg, _, _ in recorder.delivered] == [b["id"]]
    first = next(r for r in await _all() if str(r.aggregate_id) == a["id"] and r.seq == 1)
    second = next(r for r in await _all() if str(r.aggregate_id) == a["id"] and r.seq == 2)
    assert (first.status, first.attempts, first.last_error) == (PENDING, 1, "RuntimeError")
    assert first.next_attempt_at > dt.datetime.now(dt.UTC)  # backing off
    assert (second.status, second.attempts) == (PENDING, 0)  # never tried before seq 1 is delivered
    assert await relay.deliver_batch(session_factory, recorder) == 0  # still backing off
    # the cause is fixed: the retry delivers seq 1, then seq 2 (at least once)
    recorder.fail = lambda _e: False
    await _make_due()
    assert await relay.deliver_batch(session_factory, recorder) == 2
    assert [s for agg, s, _ in recorder.delivered if str(agg) == a["id"]] == [1, 2]


async def test_an_event_that_keeps_failing_is_parked_visibly_and_blocks_its_record(
    http: AsyncClient,
) -> None:
    a = await _create(http)
    await _change(http, a)
    recorder = Recorder(fail=lambda _e: True)
    for _ in range(3):
        assert await relay.deliver_one(session_factory, recorder, max_attempts=3) is True
        await _make_due()
    rows = await _all()
    assert (rows[0].status, rows[0].attempts) == (FAILED, 3)
    assert await relay.deliver_one(session_factory, recorder, max_attempts=3) is False
    assert len(recorder.started) == 3  # not retried forever, and seq 2 never overtakes it
    assert rows[1].status == PENDING and rows[1].attempts == 0
    # the owner fixes the cause and requeues it
    async with session_factory() as session:
        assert await outbox.requeue_failed(session) == 1
    ok = Recorder()
    assert await relay.deliver_batch(session_factory, ok) == 2
    assert [s for _, s, _ in ok.delivered] == [1, 2]


async def test_two_relays_never_deliver_one_event_at_the_same_time(http: AsyncClient) -> None:
    for _ in range(5):
        await _create(http)
    recorder = Recorder(delay=0.05)
    results = await asyncio.gather(*(relay.deliver_batch(session_factory, recorder) for _ in range(3)))
    assert sum(results) == 5
    assert recorder.overlap is False
    assert len(recorder.started) == len(set(recorder.started)) == 5


async def test_handlers_run_in_the_events_tenant_and_their_errors_leak_nothing(
    http: AsyncClient,
) -> None:
    seen: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    @bus.subscribe(f"{PREFIX}.created")
    async def good(event: bus.Event) -> None:
        seen.append((event.id, bus.current_tenant_id()))

    @bus.subscribe(f"{PREFIX}.created")
    async def bad(event: bus.Event) -> None:
        raise ValueError("secret-value-123")

    await _create(http)
    with capture_logs() as logs:
        await relay.deliver_one(session_factory, adapters.InProcessAdapter())
    (row,) = await _all()
    assert (row.status, row.attempts) == (PENDING, 1)
    assert row.last_error is not None
    assert "bad" in row.last_error and "ValueError" in row.last_error
    assert "secret-value-123" not in row.last_error and "secret-value-123" not in str(logs)
    assert seen == [(row.id, getattr(row, "tenant_id", None))]
    assert bus.current_tenant_id() is None  # the context does not leak out of a delivery


async def test_delivered_events_are_purged_after_the_retention(http: AsyncClient) -> None:
    for _ in range(3):
        await _create(http)
    await relay.deliver_one(session_factory, Recorder())
    await relay.deliver_one(session_factory, Recorder())
    await relay.deliver_one(session_factory, Recorder(fail=lambda _e: True), max_attempts=1)
    rows = await _all()
    assert sorted(r.status for r in rows) == [DELIVERED, DELIVERED, FAILED]
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=20)
    async with session_factory() as session:
        delivered = [r for r in rows if r.status == DELIVERED]
        await session.execute(
            sa.update(OutboxEvent).where(OutboxEvent.id == delivered[0].id).values(delivered_at=old)
        )
        await session.commit()
    async with session_factory() as session:
        assert await outbox.purge_delivered(session, retention_days=14) == 1
    left = await _all()
    assert sorted(r.status for r in left) == [DELIVERED, FAILED]  # recent and parked events stay


async def test_handled_markers_outlive_the_retention_while_their_event_may_still_be_retried(
    http: AsyncClient,
) -> None:
    await _create(http)
    (event,) = await _all()  # still pending: it can be retried
    done = uuid.uuid4()  # a marker whose event is long gone
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=100)
    mid = dt.datetime.now(dt.UTC) - dt.timedelta(days=20)  # past the retention, inside 2x
    async with session_factory() as session:
        for event_id, consumer, at in ((event.id, "c", old), (done, "old", old), (done, "mid", mid)):
            await session.execute(
                sa.text("INSERT INTO ev_handled (event_id, consumer, handled_at) VALUES (:i, :c, :t)"),
                {"i": event_id, "c": consumer, "t": at},
            )
        await session.commit()
    async with session_factory() as session:
        await outbox.purge_delivered(session, retention_days=14)
    async with session_factory() as session:
        left = set((await session.execute(sa.text("SELECT consumer FROM ev_handled"))).scalars())
    assert left == {"c", "mid"}  # "c" guards a pending event; "mid" is younger than 2x the retention
