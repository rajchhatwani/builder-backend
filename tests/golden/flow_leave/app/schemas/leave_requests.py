"""Pydantic schemas for LeaveRequest (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class LeaveRequestCreate(_pd.BaseModel):
    employee: str = _pd.Field(max_length=80)
    days: int = _pd.Field(ge=-2147483648, le=2147483647)
    balance: int = _pd.Field(ge=-2147483648, le=2147483647)


class LeaveRequestUpdate(_pd.BaseModel):
    employee: str | None = _pd.Field(default=None, max_length=80)
    days: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    balance: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("employee", "days", "balance"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class LeaveRequestRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    employee: str
    days: int
    balance: int
    state: _t.Literal['requested', 'manager_review', 'hr_review', 'approved', 'declined', 'cancelled']
    created_at: _dt.datetime
    updated_at: _dt.datetime
