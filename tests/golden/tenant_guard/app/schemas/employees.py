"""Pydantic schemas for Employee (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class EmployeeCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=120)
    salary: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    notes: str | None = _pd.Field(default=None)


class EmployeeUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    salary: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    notes: str | None = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name",):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class EmployeeRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    salary: int | None = None
    notes: str | None = None
    status: _t.Literal['draft', 'approved', 'archived']
    created_at: _dt.datetime
    updated_at: _dt.datetime
