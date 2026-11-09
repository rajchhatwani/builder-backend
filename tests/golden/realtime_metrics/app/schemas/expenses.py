"""Pydantic schemas for Expense (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class ExpenseCreate(_pd.BaseModel):
    category: str = _pd.Field(max_length=40)
    amount: _decimal.Decimal = _pd.Field(max_digits=18, decimal_places=6)
    qty: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    rate: float | None = _pd.Field(default=None)
    paid: bool | None = _pd.Field(default=None)
    cost_basis: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)
    spent_on: _dt.date | None = _pd.Field(default=None)
    logged_at: _dt.datetime | None = _pd.Field(default=None)
    code: str | None = _pd.Field(default=None, max_length=20)


class ExpenseUpdate(_pd.BaseModel):
    category: str | None = _pd.Field(default=None, max_length=40)
    amount: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)
    qty: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    rate: float | None = _pd.Field(default=None)
    paid: bool | None = _pd.Field(default=None)
    cost_basis: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)
    spent_on: _dt.date | None = _pd.Field(default=None)
    logged_at: _dt.datetime | None = _pd.Field(default=None)
    code: str | None = _pd.Field(default=None, max_length=20)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("category", "amount"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ExpenseRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    category: str
    amount: _decimal.Decimal
    qty: int | None
    rate: float | None
    paid: bool | None
    cost_basis: _decimal.Decimal | None = None
    spent_on: _dt.date | None
    logged_at: _dt.datetime | None
    code: str | None
    status: _t.Literal['draft', 'approved']
    created_at: _dt.datetime
    updated_at: _dt.datetime
