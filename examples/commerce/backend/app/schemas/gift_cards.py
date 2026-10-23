"""Pydantic schemas for GiftCard (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class GiftCardCreate(_pd.BaseModel):
    code: str = _pd.Field(max_length=32)
    initial_value: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    balance: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    currency: str = _pd.Field(max_length=3)
    expires_on: _dt.date | None = _pd.Field(default=None)
    disabled: bool | None = _pd.Field(default=False)
    note: str | None = _pd.Field(default=None)
    customer_id: _uuid.UUID | None = None


class GiftCardUpdate(_pd.BaseModel):
    code: str | None = _pd.Field(default=None, max_length=32)
    initial_value: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    balance: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    currency: str | None = _pd.Field(default=None, max_length=3)
    expires_on: _dt.date | None = _pd.Field(default=None)
    disabled: bool | None = _pd.Field(default=None)
    note: str | None = _pd.Field(default=None)
    customer_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("code", "initial_value", "balance", "currency"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class GiftCardRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    code: str
    initial_value: _decimal.Decimal
    balance: _decimal.Decimal
    currency: str
    expires_on: _dt.date | None
    disabled: bool | None
    note: str | None
    customer_id: _uuid.UUID | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
