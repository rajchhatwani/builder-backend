"""Pydantic schemas for Customer (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CustomerCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=120)
    email: str | None = _pd.Field(default=None, max_length=200)
    api_token: str | None = _pd.Field(default=None, max_length=100)


class CustomerUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    email: str | None = _pd.Field(default=None, max_length=200)
    api_token: str | None = _pd.Field(default=None, max_length=100)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name",):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CustomerRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    email: str | None
    api_token: str | None
    orders: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("orders", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
