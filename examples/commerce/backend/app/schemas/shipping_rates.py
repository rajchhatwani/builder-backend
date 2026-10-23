"""Pydantic schemas for ShippingRate (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class ShippingRateCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=120)
    price: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    min_order_subtotal: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    min_weight: float | None = _pd.Field(default=None, ge=0)
    max_weight: float | None = _pd.Field(default=None, ge=0)
    active: bool | None = _pd.Field(default=True)
    zone_id: _uuid.UUID


class ShippingRateUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    price: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    min_order_subtotal: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    min_weight: float | None = _pd.Field(default=None, ge=0)
    max_weight: float | None = _pd.Field(default=None, ge=0)
    active: bool | None = _pd.Field(default=None)
    zone_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name", "price", "zone_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ShippingRateRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    price: _decimal.Decimal
    min_order_subtotal: _decimal.Decimal | None
    min_weight: float | None
    max_weight: float | None
    active: bool | None
    zone_id: _uuid.UUID
    orders: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("orders", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
