"""Typed events (generated from the entities' Read schemas).

Each `<entity>.created / .updated / .deleted` payload carries `data`: the record as its Read schema
shows it, MINUS every field whose name looks like a credential, every json field and every relation
list (fail closed: what is not listed here is never published). `<entity>.transitioned` is announced
for entities with a state machine."""
import datetime as _dt
import uuid as _uuid

import pydantic as _pd


class TicketData(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    id: _uuid.UUID
    title: str
    priority: int | None
    created_at: _dt.datetime
    updated_at: _dt.datetime


class TicketCreated(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: TicketData


class TicketUpdated(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: TicketData
    changed: list[str]


class TicketDeleted(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: TicketData

EVENT_TYPES: dict[str, type[_pd.BaseModel]] = {
    "ticket.created": TicketCreated,
    "ticket.updated": TicketUpdated,
    "ticket.deleted": TicketDeleted,
}
