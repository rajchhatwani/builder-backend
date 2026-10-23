"""Pydantic schemas for Location (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class LocationCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=120)
    active: bool | None = _pd.Field(default=True)
    fulfills_online_orders: bool | None = _pd.Field(default=True)
    address1: str = _pd.Field(max_length=200)
    address2: str | None = _pd.Field(default=None, max_length=200)
    city: str = _pd.Field(max_length=100)
    province: str | None = _pd.Field(default=None, max_length=100)
    province_code: str | None = _pd.Field(default=None, max_length=10)
    country: str = _pd.Field(max_length=100)
    country_code: str = _pd.Field(max_length=2)
    postal_code: str | None = _pd.Field(default=None, max_length=20)
    phone: str | None = _pd.Field(default=None, max_length=30)


class LocationUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    active: bool | None = _pd.Field(default=None)
    fulfills_online_orders: bool | None = _pd.Field(default=None)
    address1: str | None = _pd.Field(default=None, max_length=200)
    address2: str | None = _pd.Field(default=None, max_length=200)
    city: str | None = _pd.Field(default=None, max_length=100)
    province: str | None = _pd.Field(default=None, max_length=100)
    province_code: str | None = _pd.Field(default=None, max_length=10)
    country: str | None = _pd.Field(default=None, max_length=100)
    country_code: str | None = _pd.Field(default=None, max_length=2)
    postal_code: str | None = _pd.Field(default=None, max_length=20)
    phone: str | None = _pd.Field(default=None, max_length=30)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name", "address1", "city", "country", "country_code"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class LocationRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    active: bool | None
    fulfills_online_orders: bool | None
    address1: str
    address2: str | None
    city: str
    province: str | None
    province_code: str | None
    country: str
    country_code: str
    postal_code: str | None
    phone: str | None
    fulfillments: list[_uuid.UUID] = _pd.Field(default_factory=list)
    inventory_levels: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("fulfillments", "inventory_levels", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
