"""Pydantic schemas for Page (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class PageCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=255)
    handle: str = _pd.Field(max_length=255)
    body_html: str | None = _pd.Field(default=None)
    published: bool | None = _pd.Field(default=False)
    template_suffix: str | None = _pd.Field(default=None, max_length=60)


class PageUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=255)
    handle: str | None = _pd.Field(default=None, max_length=255)
    body_html: str | None = _pd.Field(default=None)
    published: bool | None = _pd.Field(default=None)
    template_suffix: str | None = _pd.Field(default=None, max_length=60)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "handle"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class PageRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    handle: str
    body_html: str | None
    published: bool | None
    template_suffix: str | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
