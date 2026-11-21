"""Pydantic schemas for Appointment (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class AppointmentCreate(_pd.BaseModel):
    scheduled_at: _dt.datetime
    reason: str | None = _pd.Field(default=None, max_length=200)
    status: _t.Literal['booked', 'done', 'cancelled']
    patient_id: _uuid.UUID | None = None


class AppointmentUpdate(_pd.BaseModel):
    scheduled_at: _dt.datetime | None = _pd.Field(default=None)
    reason: str | None = _pd.Field(default=None, max_length=200)
    status: _t.Literal['booked', 'done', 'cancelled'] | None = _pd.Field(default=None)
    patient_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("scheduled_at", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class AppointmentRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    scheduled_at: _dt.datetime
    reason: str | None
    status: _t.Literal['booked', 'done', 'cancelled']
    patient_id: _uuid.UUID | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
