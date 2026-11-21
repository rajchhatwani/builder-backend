"""The event envelope, the subscriber registry and the delivery context (generated).

Contract for subscribers (app/hooks/subscribers.py):

    from app.events.bus import Event, subscribe

    @subscribe("order.created")
    async def on_order_created(event: Event) -> None:
        order = event.typed()          # the typed payload model
        ...

* Delivery is AT LEAST ONCE: a handler can see the same event again (a crash after it ran, a retry
  because a sibling handler failed). Make handlers idempotent: key on `event.id`, for instance with
  `outbox.already_handled(session, event.id, consumer)` inside the transaction that does the work.
* Events of one record (`aggregate_id`) arrive in `seq` order; a failing event holds back that record
  only. After EVENTS_MAX_ATTEMPTS the event is parked as `failed` and keeps blocking its record until
  an operator requeues it (outbox.requeue_failed).
* A handler runs inside the event's tenant: `current_tenant_id()`, and `event.tenant_id`.
* Handler errors are caught and counted as failed attempts; only the error class is logged and stored.
"""

import datetime as _dt
import importlib
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import pydantic as _pd
import structlog

from app.events.types import EVENT_TYPES

logger = structlog.get_logger()

SUBSCRIBERS_MODULE = "app.hooks.subscribers"


class Event(_pd.BaseModel):
    model_config = _pd.ConfigDict(frozen=True)

    id: uuid.UUID
    type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    seq: int
    tenant_id: uuid.UUID | None = None
    occurred_at: _dt.datetime
    payload: dict[str, Any]

    def typed(self) -> _pd.BaseModel:
        """The payload as its typed model (raises if the payload does not match: fail closed)."""
        return EVENT_TYPES[self.type].model_validate(self.payload)


Handler = Callable[[Event], Awaitable[None]]

_SUBSCRIBERS: dict[str, dict[str, Handler]] = {}
_tenant: ContextVar[uuid.UUID | None] = ContextVar("events_tenant", default=None)
_event_id: ContextVar[uuid.UUID | None] = ContextVar("events_event_id", default=None)


def consumer_name(handler: Handler) -> str:
    return f"{handler.__module__}.{handler.__qualname__}"


def subscribe(event_type: str) -> Callable[[Handler], Handler]:
    """Register a handler for one event type. An unknown event name is an error at import time."""

    def register(handler: Handler) -> Handler:
        if event_type not in EVENT_TYPES:
            known = ", ".join(sorted(EVENT_TYPES))
            raise ValueError(f"unknown event {event_type!r}; events: {known}")
        _SUBSCRIBERS.setdefault(event_type, {})[consumer_name(handler)] = handler
        return handler

    return register


def subscribers_for(event_type: str) -> list[tuple[str, Handler]]:
    return sorted(_SUBSCRIBERS.get(event_type, {}).items())


def clear_subscribers() -> None:
    """For tests."""
    _SUBSCRIBERS.clear()


def load_subscribers() -> None:
    """Import the project's subscriber module so its @subscribe decorators run (once per process)."""
    importlib.import_module(SUBSCRIBERS_MODULE)
    importlib.import_module("app.webhooks.fanout")  # platform: webhook fan-out


def current_tenant_id() -> uuid.UUID | None:
    """The tenant of the event being delivered (None outside a delivery, or for a tenant-less event)."""
    return _tenant.get()


def current_event_id() -> uuid.UUID | None:
    return _event_id.get()


def enter(event: Event) -> tuple[Any, Any]:
    return _tenant.set(event.tenant_id), _event_id.set(event.id)


def leave(tokens: tuple[Any, Any]) -> None:
    _tenant.reset(tokens[0])
    _event_id.reset(tokens[1])
