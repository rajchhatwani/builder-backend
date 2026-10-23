"""Pydantic schemas for TaxRate (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class TaxRateCreate(_pd.BaseModel):
    country_code: str = _pd.Field(max_length=2)
    province_code: str | None = _pd.Field(default=None, max_length=10)
    name: str = _pd.Field(max_length=100)
    rate: _decimal.Decimal = _pd.Field(ge=0, le=1)
    includes_shipping: bool | None = _pd.Field(default=False)


class TaxRateUpdate(_pd.BaseModel):
    country_code: str | None = _pd.Field(default=None, max_length=2)
    province_code: str | None = _pd.Field(default=None, max_length=10)
    name: str | None = _pd.Field(default=None, max_length=100)
    rate: _decimal.Decimal | None = _pd.Field(default=None, ge=0, le=1)
    includes_shipping: bool | None = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("country_code", "name", "rate"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TaxRateRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    country_code: str
    province_code: str | None
    name: str
    rate: _decimal.Decimal
    includes_shipping: bool | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
