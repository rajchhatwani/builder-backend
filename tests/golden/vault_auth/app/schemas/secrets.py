"""Pydantic schemas for Secret (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class SecretCreate(_pd.BaseModel):
    label: str = _pd.Field(max_length=80)


class SecretUpdate(_pd.BaseModel):
    label: str | None = _pd.Field(default=None, max_length=80)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("label",):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class SecretRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    label: str
    created_at: _dt.datetime
    updated_at: _dt.datetime
