"""Pydantic schemas for Store (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class StoreCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=120)
    legal_name: str | None = _pd.Field(default=None, max_length=200)
    email: str = _pd.Field(max_length=254)
    domain: str | None = _pd.Field(default=None, max_length=253)
    currency: str = _pd.Field(default='USD', max_length=3)
    timezone: str | None = _pd.Field(default='UTC', max_length=64)
    weight_unit: _t.Literal['kg', 'g', 'lb', 'oz'] | None = _pd.Field(default='kg')
    plan: _t.Literal['trial', 'basic', 'grow', 'advanced', 'plus'] | None = _pd.Field(default='trial')
    password_protected: bool | None = _pd.Field(default=False)
    settings: _t.Any = _pd.Field(default=None)


class StoreUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    legal_name: str | None = _pd.Field(default=None, max_length=200)
    email: str | None = _pd.Field(default=None, max_length=254)
    domain: str | None = _pd.Field(default=None, max_length=253)
    currency: str | None = _pd.Field(default=None, max_length=3)
    timezone: str | None = _pd.Field(default=None, max_length=64)
    weight_unit: _t.Literal['kg', 'g', 'lb', 'oz'] | None = _pd.Field(default=None)
    plan: _t.Literal['trial', 'basic', 'grow', 'advanced', 'plus'] | None = _pd.Field(default=None)
    password_protected: bool | None = _pd.Field(default=None)
    settings: _t.Any = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name", "email", "currency"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class StoreRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    legal_name: str | None
    email: str
    domain: str | None
    currency: str
    timezone: str | None
    weight_unit: _t.Literal['kg', 'g', 'lb', 'oz'] | None
    plan: _t.Literal['trial', 'basic', 'grow', 'advanced', 'plus'] | None
    password_protected: bool | None
    settings: _t.Any
    created_at: _dt.datetime
    updated_at: _dt.datetime
