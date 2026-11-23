"""Event checks (generated): the outbox is written with the change, the relay delivers at least once and in order."""

import asyncio
import datetime as dt
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa

from app.core import redact
from app.db import session_factory
from app.events import adapters, bus, config, definitions, outbox, relay
from app.events.models import PENDING, OutboxEvent
from app.events.types import EVENT_TYPES


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
