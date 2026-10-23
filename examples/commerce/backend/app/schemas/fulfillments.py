"""Pydantic schemas for Fulfillment (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class FulfillmentCreate(_pd.BaseModel):
    status: _t.Literal['pending', 'open', 'success', 'cancelled', 'error'] = _pd.Field(default='pending')
    tracking_company: str | None = _pd.Field(default=None, max_length=120)
    tracking_number: str | None = _pd.Field(default=None, max_length=120)
    tracking_url: str | None = _pd.Field(default=None, max_length=2000)
    notify_customer: bool | None = _pd.Field(default=True)
    shipped_at: _dt.datetime | None = _pd.Field(default=None)
    location_id: _uuid.UUID | None = None
    order_id: _uuid.UUID


class FulfillmentUpdate(_pd.BaseModel):
    status: _t.Literal['pending', 'open', 'success', 'cancelled', 'error'] | None = _pd.Field(default=None)
    tracking_company: str | None = _pd.Field(default=None, max_length=120)
    tracking_number: str | None = _pd.Field(default=None, max_length=120)
    tracking_url: str | None = _pd.Field(default=None, max_length=2000)
    notify_customer: bool | None = _pd.Field(default=None)
    shipped_at: _dt.datetime | None = _pd.Field(default=None)
    location_id: _uuid.UUID | None = None
    order_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("status", "order_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class FulfillmentRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    status: _t.Literal['pending', 'open', 'success', 'cancelled', 'error']
    tracking_company: str | None
    tracking_number: str | None
    tracking_url: str | None
    notify_customer: bool | None
    shipped_at: _dt.datetime | None
    location_id: _uuid.UUID | None
    order_id: _uuid.UUID
    lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("lines", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
