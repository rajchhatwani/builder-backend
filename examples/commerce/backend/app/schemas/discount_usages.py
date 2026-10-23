"""Pydantic schemas for DiscountUsage (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class DiscountUsageCreate(_pd.BaseModel):
    amount: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    email: str | None = _pd.Field(default=None, max_length=254)
    discount_id: _uuid.UUID
    order_id: _uuid.UUID


class DiscountUsageUpdate(_pd.BaseModel):
    amount: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    email: str | None = _pd.Field(default=None, max_length=254)
    discount_id: _uuid.UUID | None = None
    order_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("amount", "discount_id", "order_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class DiscountUsageRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    amount: _decimal.Decimal
    email: str | None
    discount_id: _uuid.UUID
    order_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
