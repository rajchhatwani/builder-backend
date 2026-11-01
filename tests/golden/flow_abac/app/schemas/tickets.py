"""Pydantic schemas for Ticket (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class TicketCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=120)
    priority: int = _pd.Field(ge=-2147483648, le=2147483647)
    department: str = _pd.Field(max_length=40)


class TicketUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=120)
    priority: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    department: str | None = _pd.Field(default=None, max_length=40)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "priority", "department"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TicketRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    status: _t.Literal['open', 'pending', 'closed']
    priority: int
    department: str
    created_at: _dt.datetime
    updated_at: _dt.datetime
