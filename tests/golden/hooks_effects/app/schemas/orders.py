"""Pydantic schemas for Order (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class OrderCreate(_pd.BaseModel):
    reference: str = _pd.Field(max_length=60)
    total: _decimal.Decimal = _pd.Field(max_digits=18, decimal_places=6)
    status: _t.Literal['draft', 'submitted', 'approved']
    customer_id: _uuid.UUID | None = None


class OrderUpdate(_pd.BaseModel):
    reference: str | None = _pd.Field(default=None, max_length=60)
    total: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)
    status: _t.Literal['draft', 'submitted', 'approved'] | None = _pd.Field(default=None)
    customer_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("reference", "total", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class OrderRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    reference: str
    total: _decimal.Decimal
    status: _t.Literal['draft', 'submitted', 'approved']
    customer_id: _uuid.UUID | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
