"""Pydantic schemas for Tag (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class TagCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=60)
    products: list[_uuid.UUID] = _pd.Field(default_factory=list)


class TagUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=60)
    products: list[_uuid.UUID] | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name", "products"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TagRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    products: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("products", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
