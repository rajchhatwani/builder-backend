"""Event triggers (generated): a notification type with `on_event` is queued when that event is delivered.

Imported by app/hooks/subscribers.py (and by the app itself) so the handlers are registered wherever
events are delivered. Delivery is at least once: the event id is recorded in the SAME transaction as the
delivery rows, so a repeat does nothing. A failing send never blocks the event: only a row is queued."""

from typing import Any

from app.db import session_factory
from app.events import outbox
from app.events.bus import Event, subscribe
from app.notifications import definitions, render, service


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _make(event_type: str):  # type: ignore[no-untyped-def]
    consumer = f"notifications.{event_type}"

    async def handle(event: Event) -> None:
        data = event.payload.get("data")
        if not isinstance(data, dict):
            return
        async with session_factory() as session:
            if await outbox.already_handled(session, event.id, consumer):
                await session.rollback()
                return
            for name, spec in sorted(definitions.TYPES.items()):
                if spec["on_event"] != event_type:
                    continue
                key = _text(data.get(spec["recipient_key_field"]))
                if not key:
                    continue  # no recipient on this record: nothing to send
                addresses = {c: _text(data.get(f)) for c, f in spec["address_fields"].items()}
                recipient = service.Recipient(
                    key=key, email=addresses.get("email"), phone=addresses.get("sms"), device=addresses.get("push")
                )
                values = {
                    v: (_text(data[v]) or "")[: render.MAX_VALUE]
                    for v in spec["variables"]
                    if v in data and not isinstance(data[v], dict | list)
                }
                await service.notify(
                    session, name, recipient, values, tenant_id=event.tenant_id,
                    event_id=event.id, dedupe_key=f"event:{event.id}:{name}",
                )
            await session.commit()

    handle.__name__ = handle.__qualname__ = "on_" + event_type.replace(".", "_")
    return handle


for _event in sorted({t["on_event"] for t in definitions.TYPES.values() if t["on_event"]}):
    subscribe(_event)(_make(_event))
