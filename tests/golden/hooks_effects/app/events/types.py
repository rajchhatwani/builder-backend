"""Typed events (generated from the entities' Read schemas).

Each `<entity>.created / .updated / .deleted` payload carries `data`: the record as its Read schema
shows it, MINUS every field whose name looks like a credential, every json field and every relation
list (fail closed: what is not listed here is never published). `<entity>.transitioned` is announced
for entities with a state machine."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CustomerData(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    id: _uuid.UUID
    name: str
    email: str | None
    created_at: _dt.datetime
    updated_at: _dt.datetime


class CustomerCreated(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: CustomerData


class CustomerUpdated(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: CustomerData
    changed: list[str]


class CustomerDeleted(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: CustomerData


class OrderData(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    id: _uuid.UUID
    reference: str
    total: _decimal.Decimal
    status: _t.Literal['draft', 'submitted', 'approved']
    customer_id: _uuid.UUID | None
    created_at: _dt.datetime
    updated_at: _dt.datetime


class OrderCreated(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: OrderData


class OrderUpdated(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: OrderData
    changed: list[str]


class OrderDeleted(_pd.BaseModel):
    model_config = _pd.ConfigDict(extra="forbid")

    data: OrderData

EVENT_TYPES: dict[str, type[_pd.BaseModel]] = {
    "customer.created": CustomerCreated,
    "customer.updated": CustomerUpdated,
    "customer.deleted": CustomerDeleted,
    "order.created": OrderCreated,
    "order.updated": OrderUpdated,
    "order.deleted": OrderDeleted,
}
