"""Pydantic schemas for ProductImage (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class ProductImageCreate(_pd.BaseModel):
    url: str = _pd.Field(max_length=2000)
    alt: str | None = _pd.Field(default=None, max_length=512)
    position: int | None = _pd.Field(default=1, ge=1)
    width: int | None = _pd.Field(default=None, ge=1)
    height: int | None = _pd.Field(default=None, ge=1)
    product_id: _uuid.UUID


class ProductImageUpdate(_pd.BaseModel):
    url: str | None = _pd.Field(default=None, max_length=2000)
    alt: str | None = _pd.Field(default=None, max_length=512)
    position: int | None = _pd.Field(default=None, ge=1)
    width: int | None = _pd.Field(default=None, ge=1)
    height: int | None = _pd.Field(default=None, ge=1)
    product_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("url", "product_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ProductImageRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    url: str
    alt: str | None
    position: int | None
    width: int | None
    height: int | None
    product_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
