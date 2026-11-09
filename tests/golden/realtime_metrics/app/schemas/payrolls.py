"""Pydantic schemas for Payroll (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class PayrollCreate(_pd.BaseModel):
    person: str = _pd.Field(max_length=80)
    salary: _decimal.Decimal = _pd.Field(max_digits=18, decimal_places=6)


class PayrollUpdate(_pd.BaseModel):
    person: str | None = _pd.Field(default=None, max_length=80)
    salary: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("person", "salary"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class PayrollRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    person: str
    salary: _decimal.Decimal
    created_at: _dt.datetime
    updated_at: _dt.datetime
