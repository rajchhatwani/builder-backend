"""Pydantic schemas for Post (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class PostCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=200)
    body: str
    published: bool = _pd.Field(default=False)
    views: int | None = _pd.Field(default=0, ge=0)
    author_id: _uuid.UUID
    tags: list[_uuid.UUID] = _pd.Field(default_factory=list)


class PostUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=200)
    body: str | None = _pd.Field(default=None)
    published: bool | None = _pd.Field(default=None)
    views: int | None = _pd.Field(default=None, ge=0)
    author_id: _uuid.UUID | None = None
    tags: list[_uuid.UUID] | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "body", "published", "author_id", "tags"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class PostRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    body: str
    published: bool
    views: int | None
    author_id: _uuid.UUID
    comments: list[_uuid.UUID] = _pd.Field(default_factory=list)
    tags: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("comments", "tags", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
