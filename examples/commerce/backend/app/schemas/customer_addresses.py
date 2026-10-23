"""Pydantic schemas for CustomerAddress (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CustomerAddressCreate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    company: str | None = _pd.Field(default=None, max_length=120)
    address1: str = _pd.Field(max_length=200)
    address2: str | None = _pd.Field(default=None, max_length=200)
    city: str = _pd.Field(max_length=100)
    province: str | None = _pd.Field(default=None, max_length=100)
    province_code: str | None = _pd.Field(default=None, max_length=10)
    country: str = _pd.Field(max_length=100)
    country_code: str = _pd.Field(max_length=2)
    postal_code: str | None = _pd.Field(default=None, max_length=20)
    phone: str | None = _pd.Field(default=None, max_length=30)
    is_default: bool | None = _pd.Field(default=False)
    customer_id: _uuid.UUID


class CustomerAddressUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    company: str | None = _pd.Field(default=None, max_length=120)
    address1: str | None = _pd.Field(default=None, max_length=200)
    address2: str | None = _pd.Field(default=None, max_length=200)
    city: str | None = _pd.Field(default=None, max_length=100)
    province: str | None = _pd.Field(default=None, max_length=100)
    province_code: str | None = _pd.Field(default=None, max_length=10)
    country: str | None = _pd.Field(default=None, max_length=100)
    country_code: str | None = _pd.Field(default=None, max_length=2)
    postal_code: str | None = _pd.Field(default=None, max_length=20)
    phone: str | None = _pd.Field(default=None, max_length=30)
    is_default: bool | None = _pd.Field(default=None)
    customer_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("address1", "city", "country", "country_code", "customer_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CustomerAddressRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str | None
    company: str | None
    address1: str
    address2: str | None
    city: str
    province: str | None
    province_code: str | None
    country: str
    country_code: str
    postal_code: str | None
    phone: str | None
    is_default: bool | None
    customer_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
