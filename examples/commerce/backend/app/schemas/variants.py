"""Pydantic schemas for Variant (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class VariantCreate(_pd.BaseModel):
    title: str = _pd.Field(default='Default', max_length=255)
    sku: str | None = _pd.Field(default=None, max_length=100)
    barcode: str | None = _pd.Field(default=None, max_length=64)
    price: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    compare_at_price: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    cost: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    weight: float | None = _pd.Field(default=None, ge=0)
    position: int | None = _pd.Field(default=1, ge=1)
    option1: str | None = _pd.Field(default=None, max_length=255)
    option2: str | None = _pd.Field(default=None, max_length=255)
    option3: str | None = _pd.Field(default=None, max_length=255)
    taxable: bool | None = _pd.Field(default=True)
    requires_shipping: bool | None = _pd.Field(default=True)
    inventory_policy: _t.Literal['deny', 'continue'] | None = _pd.Field(default='deny')
    inventory_tracked: bool | None = _pd.Field(default=True)
    product_id: _uuid.UUID


class VariantUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=255)
    sku: str | None = _pd.Field(default=None, max_length=100)
    barcode: str | None = _pd.Field(default=None, max_length=64)
    price: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    compare_at_price: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    cost: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    weight: float | None = _pd.Field(default=None, ge=0)
    position: int | None = _pd.Field(default=None, ge=1)
    option1: str | None = _pd.Field(default=None, max_length=255)
    option2: str | None = _pd.Field(default=None, max_length=255)
    option3: str | None = _pd.Field(default=None, max_length=255)
    taxable: bool | None = _pd.Field(default=None)
    requires_shipping: bool | None = _pd.Field(default=None)
    inventory_policy: _t.Literal['deny', 'continue'] | None = _pd.Field(default=None)
    inventory_tracked: bool | None = _pd.Field(default=None)
    product_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "price", "product_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class VariantRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    sku: str | None
    barcode: str | None
    price: _decimal.Decimal
    compare_at_price: _decimal.Decimal | None
    cost: _decimal.Decimal | None
    weight: float | None
    position: int | None
    option1: str | None
    option2: str | None
    option3: str | None
    taxable: bool | None
    requires_shipping: bool | None
    inventory_policy: _t.Literal['deny', 'continue'] | None
    inventory_tracked: bool | None
    product_id: _uuid.UUID
    cart_lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    inventory_levels: list[_uuid.UUID] = _pd.Field(default_factory=list)
    order_lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("cart_lines", "inventory_levels", "order_lines", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
