"""Pydantic schemas for Document (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class DocumentCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=120)
    status: _t.Literal['draft', 'published', 'archived']
    pages: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)


class DocumentUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=120)
    status: _t.Literal['draft', 'published', 'archived'] | None = _pd.Field(default=None)
    pages: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class DocumentRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    status: _t.Literal['draft', 'published', 'archived']
    pages: int | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
