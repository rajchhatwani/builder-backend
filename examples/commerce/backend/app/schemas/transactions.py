"""Pydantic schemas for Transaction (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class TransactionCreate(_pd.BaseModel):
    kind: _t.Literal['authorization', 'capture', 'sale', 'void', 'refund']
    status: _t.Literal['pending', 'success', 'failure', 'error']
    amount: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    currency: str = _pd.Field(max_length=3)
    gateway: str | None = _pd.Field(default=None, max_length=60)
    reference: str | None = _pd.Field(default=None, max_length=120)
    error_code: str | None = _pd.Field(default=None, max_length=60)
    processed_at: _dt.datetime | None = _pd.Field(default=None)
    order_id: _uuid.UUID


class TransactionUpdate(_pd.BaseModel):
    kind: _t.Literal['authorization', 'capture', 'sale', 'void', 'refund'] | None = _pd.Field(default=None)
    status: _t.Literal['pending', 'success', 'failure', 'error'] | None = _pd.Field(default=None)
    amount: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    currency: str | None = _pd.Field(default=None, max_length=3)
    gateway: str | None = _pd.Field(default=None, max_length=60)
    reference: str | None = _pd.Field(default=None, max_length=120)
    error_code: str | None = _pd.Field(default=None, max_length=60)
    processed_at: _dt.datetime | None = _pd.Field(default=None)
    order_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("kind", "status", "amount", "currency", "order_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TransactionRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    kind: _t.Literal['authorization', 'capture', 'sale', 'void', 'refund']
    status: _t.Literal['pending', 'success', 'failure', 'error']
    amount: _decimal.Decimal
    currency: str
    gateway: str | None
    reference: str | None
    error_code: str | None
    processed_at: _dt.datetime | None
    order_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
