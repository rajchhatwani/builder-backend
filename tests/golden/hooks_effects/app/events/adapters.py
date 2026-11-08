"""Where delivered events go (generated). The relay only knows the `EventAdapter` interface.

`in_process` runs the subscribers inside the same app. Other adapters (Redis Streams, Kafka, RabbitMQ)
plug in by implementing `publish`: it must return only when the broker has accepted the event, and
raise otherwise, so the outbox row stays pending and is retried."""

import asyncio
from typing import Protocol

import structlog

from app.events import bus, config

logger = structlog.get_logger()


class DeliveryFailed(Exception):
    """One or more subscribers failed. The message names consumers and error classes, never payloads."""

    def __init__(self, failures: list[tuple[str, str]]) -> None:
        self.failures = failures
        super().__init__("; ".join(f"{consumer}: {error}" for consumer, error in failures))


class EventAdapter(Protocol):
    name: str

    async def publish(self, event: bus.Event) -> None: ...

    async def close(self) -> None: ...


class InProcessAdapter:
    name = "in_process"

    async def publish(self, event: bus.Event) -> None:
        failures: list[tuple[str, str]] = []
        tokens = bus.enter(event)
        try:
            for consumer, handler in bus.subscribers_for(event.type):
                try:
                    await asyncio.wait_for(handler(event), config.handler_timeout())
                except Exception as exc:
                    failures.append((consumer, type(exc).__name__))
                    logger.error(
                        "event_handler_failed",
                        event_id=str(event.id),
                        event_type=event.type,
                        consumer=consumer,
                        error=type(exc).__name__,
                    )
        finally:
            bus.leave(tokens)
        if failures:
            raise DeliveryFailed(failures)

    async def close(self) -> None:
        return None


class RedisStreamsAdapter:
    """Interface stub: not implemented yet (spec validation refuses `redis_streams` for now)."""

    name = "redis_streams"

    def __init__(self) -> None:
        raise NotImplementedError(
            "the redis_streams adapter is not implemented yet: use the in_process adapter"
        )

    async def publish(self, event: bus.Event) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None


def make_adapter(name: str) -> EventAdapter:
    if name == "in_process":
        return InProcessAdapter()
    if name == "redis_streams":
        return RedisStreamsAdapter()
    raise ValueError(f"unknown event adapter {name!r}")
