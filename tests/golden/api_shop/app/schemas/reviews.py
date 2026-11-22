"""Pydantic schemas for Review (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class ReviewCreate(_pd.BaseModel):
    stars: int = _pd.Field(ge=-2147483648, le=2147483647)
    body: str | None = _pd.Field(default=None, max_length=300)


class ReviewUpdate(_pd.BaseModel):
    stars: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    body: str | None = _pd.Field(default=None, max_length=300)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("stars",):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ReviewRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    stars: int
    body: str | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
