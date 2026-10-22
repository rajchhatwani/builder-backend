"""Pydantic schemas for Author (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class AuthorCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=80)
    bio: str | None = _pd.Field(default=None)
    born_on: _dt.date | None = _pd.Field(default=None)
    rating: float | None = _pd.Field(default=None, ge=0, le=5)


class AuthorUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=80)
    bio: str | None = _pd.Field(default=None)
    born_on: _dt.date | None = _pd.Field(default=None)
    rating: float | None = _pd.Field(default=None, ge=0, le=5)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name",):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class AuthorRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    bio: str | None
    born_on: _dt.date | None
    rating: float | None
    books: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("books", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
