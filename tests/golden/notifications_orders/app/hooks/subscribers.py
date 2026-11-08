"""Your event subscribers. Written once; the platform never overwrites this file.

    from app.events.bus import Event, subscribe

    @subscribe("order.created")
    async def notify_sales(event: Event) -> None:
        order = event.typed()   # typed payload (see app/events/types.py)
        ...

Delivery is at least once: make handlers idempotent (key on event.id; see app.events.outbox.already_handled).
An unknown event name stops the app at start-up.
"""

# Generated notifications are queued by these triggers: keep this import.
import app.notifications.triggers  # noqa: E402,F401
