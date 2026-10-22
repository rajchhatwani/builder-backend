"""Pydantic schemas for Profile (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class ProfileCreate(_pd.BaseModel):
    bio: str
    member_id: _uuid.UUID


class ProfileUpdate(_pd.BaseModel):
    bio: str | None = _pd.Field(default=None)
    member_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("bio", "member_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ProfileRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    bio: str
    member_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
