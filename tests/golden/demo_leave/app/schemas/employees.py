"""Pydantic schemas for Employee (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class EmployeeCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=80)
    email: str = _pd.Field(max_length=120)
    department: str | None = _pd.Field(default=None, max_length=60)
    leave_balance: int = _pd.Field(ge=0, le=2147483647)


class EmployeeUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=80)
    email: str | None = _pd.Field(default=None, max_length=120)
    department: str | None = _pd.Field(default=None, max_length=60)
    leave_balance: int | None = _pd.Field(default=None, ge=0, le=2147483647)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name", "email", "leave_balance"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class EmployeeRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    email: str
    department: str | None
    leave_balance: int
    leave_requests: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("leave_requests", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
