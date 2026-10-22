"""Pydantic schemas for Member (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class MemberCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=80)
    email: str = _pd.Field(max_length=120)
    joined_on: _dt.date | None = _pd.Field(default=_dt.date.fromisoformat('2026-01-01'))
    sponsor_id: _uuid.UUID | None = None
    borrowed_books: list[_uuid.UUID] = _pd.Field(default_factory=list)


class MemberUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=80)
    email: str | None = _pd.Field(default=None, max_length=120)
    joined_on: _dt.date | None = _pd.Field(default=None)
    sponsor_id: _uuid.UUID | None = None
    borrowed_books: list[_uuid.UUID] | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name", "email", "borrowed_books"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class MemberRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    email: str
    joined_on: _dt.date | None
    sponsor_id: _uuid.UUID | None
    borrowed_books: list[_uuid.UUID] = _pd.Field(default_factory=list)
    profile: _uuid.UUID | None = None
    sponsored: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("borrowed_books", "sponsored", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]

    @_pd.field_validator("profile", mode="before")
    @classmethod
    def coerce_single_id(cls, value: _t.Any) -> _t.Any:
        return None if value is None else value.id
