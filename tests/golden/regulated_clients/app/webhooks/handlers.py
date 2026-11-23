"""Incoming webhook handlers: the registry and the context a handler receives (generated).

Write handlers in app/hooks/webhooks.py (yours, never overwritten):

    from app.webhooks.handlers import InboundContext, inbound

    @inbound("payments")                      # the endpoint's name in the spec
    async def on_payments(ctx: InboundContext) -> None:
        event = ctx.json()
        ...                                   # write through ctx.session: it commits with the dedupe record

A handler only ever sees a request whose signature, timestamp and delivery id were verified and that was not
seen before. It runs in the same transaction as the dedupe record: if it raises, nothing is recorded and the
sender's retry runs it again. Do not log the body wholesale.
"""

import importlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.webhooks import definitions

HANDLERS_MODULE = "app.hooks.webhooks"


@dataclass(frozen=True)
class InboundContext:
    endpoint: str
    tenant_id: uuid.UUID | None
    delivery_id: str
    body: bytes
    session: AsyncSession

    def json(self) -> Any:
        return json.loads(self.body)


Handler = Callable[[InboundContext], Awaitable[None]]
_HANDLERS: dict[str, Handler] = {}


def inbound(endpoint: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if endpoint not in definitions.INBOUND:
            raise ValueError(f"unknown incoming endpoint {endpoint!r}: declare it in the spec first")
        if endpoint in _HANDLERS and _HANDLERS[endpoint] is not fn:
            raise ValueError(f"endpoint {endpoint!r} already has a handler")
        _HANDLERS[endpoint] = fn
        return fn

    return register


def get(endpoint: str) -> Handler | None:
    return _HANDLERS.get(endpoint)


def clear_handlers() -> None:
    """For tests."""
    _HANDLERS.clear()


def load_handlers() -> None:
    importlib.import_module(HANDLERS_MODULE)
