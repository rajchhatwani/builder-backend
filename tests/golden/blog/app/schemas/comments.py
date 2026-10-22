"""Pydantic schemas for Comment (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CommentCreate(_pd.BaseModel):
    body: str
    post_id: _uuid.UUID


class CommentUpdate(_pd.BaseModel):
    body: str | None = _pd.Field(default=None)
    post_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("body", "post_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CommentRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    body: str
    post_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
