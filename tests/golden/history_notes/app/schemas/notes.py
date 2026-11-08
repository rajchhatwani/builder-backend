"""Pydantic schemas for Note (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class NoteCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=120)
    body: str | None = _pd.Field(default=None)
    payload: _t.Any = _pd.Field(default=None)
    private_note: str | None = _pd.Field(default=None)


class NoteUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=120)
    body: str | None = _pd.Field(default=None)
    payload: _t.Any = _pd.Field(default=None)
    private_note: str | None = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title",):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class NoteRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    body: str | None
    payload: _t.Any
    private_note: str | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
