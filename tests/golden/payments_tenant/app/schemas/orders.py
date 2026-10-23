"""Pydantic schemas for Order (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class OrderCreate(_pd.BaseModel):
    total: _decimal.Decimal = _pd.Field(ge=0.01, le=100000, max_digits=18, decimal_places=6)
    currency: str = _pd.Field(max_length=3)
    state: _t.Literal['open', 'settled', 'part_refunded', 'refunded'] = _pd.Field(default='open')


class OrderUpdate(_pd.BaseModel):
    total: _decimal.Decimal | None = _pd.Field(default=None, ge=0.01, le=100000, max_digits=18, decimal_places=6)
    currency: str | None = _pd.Field(default=None, max_length=3)
    state: _t.Literal['open', 'settled', 'part_refunded', 'refunded'] | None = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("total", "currency", "state"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class OrderRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    total: _decimal.Decimal
    currency: str
    state: _t.Literal['open', 'settled', 'part_refunded', 'refunded']
    created_at: _dt.datetime
    updated_at: _dt.datetime
