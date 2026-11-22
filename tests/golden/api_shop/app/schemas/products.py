"""Pydantic schemas for Product (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class ProductCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=120)
    price_cents: int = _pd.Field(ge=-2147483648, le=2147483647)
    internal_cost: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)


class ProductUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=120)
    price_cents: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    internal_cost: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "price_cents"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ProductRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    price_cents: int
    internal_cost: int | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
