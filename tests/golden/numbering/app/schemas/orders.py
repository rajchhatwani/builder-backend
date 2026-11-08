"""Pydantic schemas for Order (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class OrderCreate(_pd.BaseModel):
    customer: str = _pd.Field(max_length=120)
    total: _decimal.Decimal = _pd.Field(max_digits=18, decimal_places=6)


class OrderUpdate(_pd.BaseModel):
    customer: str | None = _pd.Field(default=None, max_length=120)
    total: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("customer", "total"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class OrderRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    customer: str
    total: _decimal.Decimal
    stage: _t.Literal['open', 'auto_approved', 'needs_review']
    invoice_no: str
    order_no: str
    ticket_no: int
    created_at: _dt.datetime
    updated_at: _dt.datetime
