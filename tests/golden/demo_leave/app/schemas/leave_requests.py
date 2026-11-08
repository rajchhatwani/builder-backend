"""Pydantic schemas for LeaveRequest (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class LeaveRequestCreate(_pd.BaseModel):
    start_date: _dt.date
    end_date: _dt.date
    days: int = _pd.Field(ge=1, le=60)
    balance: int = _pd.Field(ge=0, le=2147483647)
    reason: str | None = _pd.Field(default=None, max_length=200)
    employee_id: _uuid.UUID


class LeaveRequestUpdate(_pd.BaseModel):
    start_date: _dt.date | None = _pd.Field(default=None)
    end_date: _dt.date | None = _pd.Field(default=None)
    days: int | None = _pd.Field(default=None, ge=1, le=60)
    balance: int | None = _pd.Field(default=None, ge=0, le=2147483647)
    reason: str | None = _pd.Field(default=None, max_length=200)
    employee_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("start_date", "end_date", "days", "balance", "employee_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class LeaveRequestRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    request_no: str
    start_date: _dt.date
    end_date: _dt.date
    days: int
    balance: int
    reason: str | None
    state: _t.Literal['requested', 'manager_review', 'hr_review', 'approved', 'declined', 'cancelled']
    employee_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
