"""Pydantic schemas for OrderEvent (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class OrderEventCreate(_pd.BaseModel):
    verb: _t.Literal['placed', 'paid', 'fulfilled', 'refunded', 'cancelled', 'note', 'email_sent', 'edited']
    message: str | None = _pd.Field(default=None)
    actor: str | None = _pd.Field(default=None, max_length=254)
    data: _t.Any = _pd.Field(default=None)
    order_id: _uuid.UUID


class OrderEventUpdate(_pd.BaseModel):
    verb: _t.Literal['placed', 'paid', 'fulfilled', 'refunded', 'cancelled', 'note', 'email_sent', 'edited'] | None = _pd.Field(default=None)
    message: str | None = _pd.Field(default=None)
    actor: str | None = _pd.Field(default=None, max_length=254)
    data: _t.Any = _pd.Field(default=None)
    order_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("verb", "order_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class OrderEventRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    verb: _t.Literal['placed', 'paid', 'fulfilled', 'refunded', 'cancelled', 'note', 'email_sent', 'edited']
    message: str | None
    actor: str | None
    data: _t.Any
    order_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
