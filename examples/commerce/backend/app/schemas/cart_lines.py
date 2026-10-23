"""Pydantic schemas for CartLine (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CartLineCreate(_pd.BaseModel):
    quantity: int = _pd.Field(default=1, ge=1, le=10000)
    properties: _t.Any = _pd.Field(default=None)
    cart_id: _uuid.UUID
    variant_id: _uuid.UUID


class CartLineUpdate(_pd.BaseModel):
    quantity: int | None = _pd.Field(default=None, ge=1, le=10000)
    properties: _t.Any = _pd.Field(default=None)
    cart_id: _uuid.UUID | None = None
    variant_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("quantity", "cart_id", "variant_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CartLineRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    quantity: int
    properties: _t.Any
    cart_id: _uuid.UUID
    variant_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
