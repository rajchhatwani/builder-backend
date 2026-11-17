"""Pydantic schemas for OrderLine (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class OrderLineCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=255)
    variant_title: str | None = _pd.Field(default=None, max_length=255)
    sku: str | None = _pd.Field(default=None, max_length=100)
    quantity: int = _pd.Field(ge=1)
    unit_price: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    discount_total: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    tax_total: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    fulfilled_quantity: int | None = _pd.Field(default=0, ge=0)
    refunded_quantity: int | None = _pd.Field(default=0, ge=0)
    properties: _t.Any = _pd.Field(default=None)
    order_id: _uuid.UUID
    variant_id: _uuid.UUID | None = None


class OrderLineUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=255)
    variant_title: str | None = _pd.Field(default=None, max_length=255)
    sku: str | None = _pd.Field(default=None, max_length=100)
    quantity: int | None = _pd.Field(default=None, ge=1)
    unit_price: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    discount_total: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    tax_total: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    fulfilled_quantity: int | None = _pd.Field(default=None, ge=0)
    refunded_quantity: int | None = _pd.Field(default=None, ge=0)
    properties: _t.Any = _pd.Field(default=None)
    order_id: _uuid.UUID | None = None
    variant_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "quantity", "unit_price", "order_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class OrderLineRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    variant_title: str | None
    sku: str | None
    quantity: int
    unit_price: _decimal.Decimal
    discount_total: _decimal.Decimal | None
    tax_total: _decimal.Decimal | None
    fulfilled_quantity: int | None
    refunded_quantity: int | None
    properties: _t.Any
    order_id: _uuid.UUID
    variant_id: _uuid.UUID | None
    fulfillment_lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    refund_lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("fulfillment_lines", "refund_lines", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
