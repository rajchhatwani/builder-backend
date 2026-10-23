"""Pydantic schemas for Order (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class OrderCreate(_pd.BaseModel):
    number: int = _pd.Field(ge=1)
    email: str | None = _pd.Field(default=None, max_length=254)
    status: _t.Literal['open', 'closed', 'cancelled'] = _pd.Field(default='open')
    financial_status: _t.Literal['pending', 'authorized', 'partially_paid', 'paid', 'partially_refunded', 'refunded', 'voided'] | None = _pd.Field(default='pending')
    fulfillment_status: _t.Literal['unfulfilled', 'partial', 'fulfilled', 'restocked'] | None = _pd.Field(default='unfulfilled')
    currency: str = _pd.Field(default='USD', max_length=3)
    subtotal: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    shipping_total: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    tax_total: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    discount_total: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    total: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    total_refunded: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    billing_address: _t.Any = _pd.Field(default=None)
    shipping_address: _t.Any = _pd.Field(default=None)
    shipping_method: str | None = _pd.Field(default=None, max_length=120)
    discount_code: str | None = _pd.Field(default=None, max_length=64)
    note: str | None = _pd.Field(default=None)
    tags_cache: _t.Any = _pd.Field(default=None)
    source: str | None = _pd.Field(default='web', max_length=60)
    placed_at: _dt.datetime
    closed_at: _dt.datetime | None = _pd.Field(default=None)
    cancelled_at: _dt.datetime | None = _pd.Field(default=None)
    cancel_reason: _t.Literal['customer', 'fraud', 'inventory', 'declined', 'other'] | None = _pd.Field(default=None)
    cart_id: _uuid.UUID | None = None
    customer_id: _uuid.UUID | None = None
    shipping_rate_id: _uuid.UUID | None = None


class OrderUpdate(_pd.BaseModel):
    number: int | None = _pd.Field(default=None, ge=1)
    email: str | None = _pd.Field(default=None, max_length=254)
    status: _t.Literal['open', 'closed', 'cancelled'] | None = _pd.Field(default=None)
    financial_status: _t.Literal['pending', 'authorized', 'partially_paid', 'paid', 'partially_refunded', 'refunded', 'voided'] | None = _pd.Field(default=None)
    fulfillment_status: _t.Literal['unfulfilled', 'partial', 'fulfilled', 'restocked'] | None = _pd.Field(default=None)
    currency: str | None = _pd.Field(default=None, max_length=3)
    subtotal: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    shipping_total: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    tax_total: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    discount_total: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    total: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    total_refunded: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    billing_address: _t.Any = _pd.Field(default=None)
    shipping_address: _t.Any = _pd.Field(default=None)
    shipping_method: str | None = _pd.Field(default=None, max_length=120)
    discount_code: str | None = _pd.Field(default=None, max_length=64)
    note: str | None = _pd.Field(default=None)
    tags_cache: _t.Any = _pd.Field(default=None)
    source: str | None = _pd.Field(default=None, max_length=60)
    placed_at: _dt.datetime | None = _pd.Field(default=None)
    closed_at: _dt.datetime | None = _pd.Field(default=None)
    cancelled_at: _dt.datetime | None = _pd.Field(default=None)
    cancel_reason: _t.Literal['customer', 'fraud', 'inventory', 'declined', 'other'] | None = _pd.Field(default=None)
    cart_id: _uuid.UUID | None = None
    customer_id: _uuid.UUID | None = None
    shipping_rate_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("number", "status", "currency", "subtotal", "total", "placed_at"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class OrderRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    number: int
    email: str | None
    status: _t.Literal['open', 'closed', 'cancelled']
    financial_status: _t.Literal['pending', 'authorized', 'partially_paid', 'paid', 'partially_refunded', 'refunded', 'voided'] | None
    fulfillment_status: _t.Literal['unfulfilled', 'partial', 'fulfilled', 'restocked'] | None
    currency: str
    subtotal: _decimal.Decimal
    shipping_total: _decimal.Decimal | None
    tax_total: _decimal.Decimal | None
    discount_total: _decimal.Decimal | None
    total: _decimal.Decimal
    total_refunded: _decimal.Decimal | None
    billing_address: _t.Any
    shipping_address: _t.Any
    shipping_method: str | None
    discount_code: str | None
    note: str | None
    tags_cache: _t.Any
    source: str | None
    placed_at: _dt.datetime
    closed_at: _dt.datetime | None
    cancelled_at: _dt.datetime | None
    cancel_reason: _t.Literal['customer', 'fraud', 'inventory', 'declined', 'other'] | None
    cart_id: _uuid.UUID | None
    customer_id: _uuid.UUID | None
    shipping_rate_id: _uuid.UUID | None
    discount_usages: list[_uuid.UUID] = _pd.Field(default_factory=list)
    events: list[_uuid.UUID] = _pd.Field(default_factory=list)
    fulfillments: list[_uuid.UUID] = _pd.Field(default_factory=list)
    lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    refunds: list[_uuid.UUID] = _pd.Field(default_factory=list)
    transactions: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("discount_usages", "events", "fulfillments", "lines", "refunds", "transactions", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
