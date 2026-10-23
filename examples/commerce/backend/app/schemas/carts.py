"""Pydantic schemas for Cart (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CartCreate(_pd.BaseModel):
    token: str = _pd.Field(max_length=64)
    email: str | None = _pd.Field(default=None, max_length=254)
    currency: str = _pd.Field(default='USD', max_length=3)
    status: _t.Literal['open', 'abandoned', 'converted'] | None = _pd.Field(default='open')
    discount_code: str | None = _pd.Field(default=None, max_length=64)
    note: str | None = _pd.Field(default=None)
    attributes: _t.Any = _pd.Field(default=None)
    expires_at: _dt.datetime | None = _pd.Field(default=None)
    customer_id: _uuid.UUID | None = None


class CartUpdate(_pd.BaseModel):
    token: str | None = _pd.Field(default=None, max_length=64)
    email: str | None = _pd.Field(default=None, max_length=254)
    currency: str | None = _pd.Field(default=None, max_length=3)
    status: _t.Literal['open', 'abandoned', 'converted'] | None = _pd.Field(default=None)
    discount_code: str | None = _pd.Field(default=None, max_length=64)
    note: str | None = _pd.Field(default=None)
    attributes: _t.Any = _pd.Field(default=None)
    expires_at: _dt.datetime | None = _pd.Field(default=None)
    customer_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("token", "currency"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CartRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    token: str
    email: str | None
    currency: str
    status: _t.Literal['open', 'abandoned', 'converted'] | None
    discount_code: str | None
    note: str | None
    attributes: _t.Any
    expires_at: _dt.datetime | None
    customer_id: _uuid.UUID | None
    lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    order: _uuid.UUID | None = None
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("lines", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]

    @_pd.field_validator("order", mode="before")
    @classmethod
    def coerce_single_id(cls, value: _t.Any) -> _t.Any:
        return None if value is None else value.id
