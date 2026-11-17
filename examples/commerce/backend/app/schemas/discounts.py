"""Pydantic schemas for Discount (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class DiscountCreate(_pd.BaseModel):
    code: str = _pd.Field(max_length=64)
    title: str | None = _pd.Field(default=None, max_length=120)
    kind: _t.Literal['percentage', 'fixed_amount', 'free_shipping', 'buy_x_get_y']
    value: _decimal.Decimal = _pd.Field(ge=0)
    target: _t.Literal['order', 'line_item', 'shipping'] | None = _pd.Field(default='order')
    minimum_subtotal: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    usage_limit: int | None = _pd.Field(default=None, ge=1)
    once_per_customer: bool | None = _pd.Field(default=False)
    used_count: int | None = _pd.Field(default=0, ge=0)
    combines_with_other: bool | None = _pd.Field(default=False)
    applies_to: _t.Any = _pd.Field(default=None)
    starts_at: _dt.datetime | None = _pd.Field(default=None)
    ends_at: _dt.datetime | None = _pd.Field(default=None)
    active: bool | None = _pd.Field(default=True)


class DiscountUpdate(_pd.BaseModel):
    code: str | None = _pd.Field(default=None, max_length=64)
    title: str | None = _pd.Field(default=None, max_length=120)
    kind: _t.Literal['percentage', 'fixed_amount', 'free_shipping', 'buy_x_get_y'] | None = _pd.Field(default=None)
    value: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    target: _t.Literal['order', 'line_item', 'shipping'] | None = _pd.Field(default=None)
    minimum_subtotal: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    usage_limit: int | None = _pd.Field(default=None, ge=1)
    once_per_customer: bool | None = _pd.Field(default=None)
    used_count: int | None = _pd.Field(default=None, ge=0)
    combines_with_other: bool | None = _pd.Field(default=None)
    applies_to: _t.Any = _pd.Field(default=None)
    starts_at: _dt.datetime | None = _pd.Field(default=None)
    ends_at: _dt.datetime | None = _pd.Field(default=None)
    active: bool | None = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("code", "kind", "value"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class DiscountRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    code: str
    title: str | None
    kind: _t.Literal['percentage', 'fixed_amount', 'free_shipping', 'buy_x_get_y']
    value: _decimal.Decimal
    target: _t.Literal['order', 'line_item', 'shipping'] | None
    minimum_subtotal: _decimal.Decimal | None
    usage_limit: int | None
    once_per_customer: bool | None
    used_count: int | None
    combines_with_other: bool | None
    applies_to: _t.Any
    starts_at: _dt.datetime | None
    ends_at: _dt.datetime | None
    active: bool | None
    usages: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("usages", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
