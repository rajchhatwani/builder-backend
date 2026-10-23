"""Pydantic schemas for Webhook (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class WebhookCreate(_pd.BaseModel):
    topic: _t.Literal['orders.create', 'orders.paid', 'orders.cancelled', 'products.create', 'products.update', 'customers.create', 'refunds.create', 'fulfillments.create']
    url: str = _pd.Field(max_length=2000)
    body_format: _t.Literal['json', 'xml'] | None = _pd.Field(default='json')
    secret: str | None = _pd.Field(default=None, max_length=128)
    active: bool | None = _pd.Field(default=True)


class WebhookUpdate(_pd.BaseModel):
    topic: _t.Literal['orders.create', 'orders.paid', 'orders.cancelled', 'products.create', 'products.update', 'customers.create', 'refunds.create', 'fulfillments.create'] | None = _pd.Field(default=None)
    url: str | None = _pd.Field(default=None, max_length=2000)
    body_format: _t.Literal['json', 'xml'] | None = _pd.Field(default=None)
    secret: str | None = _pd.Field(default=None, max_length=128)
    active: bool | None = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("topic", "url"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class WebhookRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    topic: _t.Literal['orders.create', 'orders.paid', 'orders.cancelled', 'products.create', 'products.update', 'customers.create', 'refunds.create', 'fulfillments.create']
    url: str
    body_format: _t.Literal['json', 'xml'] | None
    secret: str | None
    active: bool | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
