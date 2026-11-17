"""Pydantic schemas for Customer (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CustomerCreate(_pd.BaseModel):
    email: str | None = _pd.Field(default=None, max_length=254)
    first_name: str | None = _pd.Field(default=None, max_length=100)
    last_name: str | None = _pd.Field(default=None, max_length=100)
    phone: str | None = _pd.Field(default=None, max_length=30)
    state: _t.Literal['enabled', 'disabled', 'invited', 'declined'] | None = _pd.Field(default='enabled')
    accepts_marketing: bool | None = _pd.Field(default=False)
    accepts_marketing_updated_at: _dt.datetime | None = _pd.Field(default=None)
    tax_exempt: bool | None = _pd.Field(default=False)
    total_spent: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    orders_count: int | None = _pd.Field(default=0, ge=0)
    tags_cache: _t.Any = _pd.Field(default=None)
    note: str | None = _pd.Field(default=None)
    locale: str | None = _pd.Field(default=None, max_length=10)


class CustomerUpdate(_pd.BaseModel):
    email: str | None = _pd.Field(default=None, max_length=254)
    first_name: str | None = _pd.Field(default=None, max_length=100)
    last_name: str | None = _pd.Field(default=None, max_length=100)
    phone: str | None = _pd.Field(default=None, max_length=30)
    state: _t.Literal['enabled', 'disabled', 'invited', 'declined'] | None = _pd.Field(default=None)
    accepts_marketing: bool | None = _pd.Field(default=None)
    accepts_marketing_updated_at: _dt.datetime | None = _pd.Field(default=None)
    tax_exempt: bool | None = _pd.Field(default=None)
    total_spent: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    orders_count: int | None = _pd.Field(default=None, ge=0)
    tags_cache: _t.Any = _pd.Field(default=None)
    note: str | None = _pd.Field(default=None)
    locale: str | None = _pd.Field(default=None, max_length=10)


class CustomerRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    email: str | None
    first_name: str | None
    last_name: str | None
    phone: str | None
    state: _t.Literal['enabled', 'disabled', 'invited', 'declined'] | None
    accepts_marketing: bool | None
    accepts_marketing_updated_at: _dt.datetime | None
    tax_exempt: bool | None
    total_spent: _decimal.Decimal | None
    orders_count: int | None
    tags_cache: _t.Any
    note: str | None
    locale: str | None
    addresses: list[_uuid.UUID] = _pd.Field(default_factory=list)
    carts: list[_uuid.UUID] = _pd.Field(default_factory=list)
    gift_cards: list[_uuid.UUID] = _pd.Field(default_factory=list)
    orders: list[_uuid.UUID] = _pd.Field(default_factory=list)
    reviews: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("addresses", "carts", "gift_cards", "orders", "reviews", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
