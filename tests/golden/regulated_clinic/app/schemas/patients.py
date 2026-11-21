"""Pydantic schemas for Patient (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class PatientCreate(_pd.BaseModel):
    name: str = _pd.Field(max_length=120)
    dob: str | None = _pd.Field(default=None, max_length=20)
    phone: str | None = _pd.Field(default=None, max_length=30)
    postcode: str | None = _pd.Field(default=None, max_length=10)
    age: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    notes: str | None = _pd.Field(default=None)
    insurance_no: str | None = _pd.Field(default=None, max_length=40)


class PatientUpdate(_pd.BaseModel):
    name: str | None = _pd.Field(default=None, max_length=120)
    dob: str | None = _pd.Field(default=None, max_length=20)
    phone: str | None = _pd.Field(default=None, max_length=30)
    postcode: str | None = _pd.Field(default=None, max_length=10)
    age: int | None = _pd.Field(default=None, ge=-2147483648, le=2147483647)
    notes: str | None = _pd.Field(default=None)
    insurance_no: str | None = _pd.Field(default=None, max_length=40)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("name",):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class PatientRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str
    dob: str | None
    phone: str | None
    postcode: str | None
    age: int | None
    notes: str | None
    insurance_no: str | None
    appointments: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("appointments", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
