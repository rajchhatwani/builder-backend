"""Pydantic schemas for Contact (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd

from app.core import custom_fields as _custom_fields

_CUSTOM_DEFS = (('birthday', 'date', False, None, None), ('last_seen', 'datetime', False, None, None), ('nickname', 'string', False, 40, None), ('rating', 'float', False, None, None), ('score', 'int', False, None, None), ('tier', 'string', True, None, ('gold', 'silver')), ('vip', 'bool', False, None, None))


class ContactCreate(_pd.BaseModel):
    full_name: str = _pd.Field(max_length=120)
    custom_fields: dict[str, _t.Any] = _pd.Field(default_factory=dict)

    @_pd.field_validator("custom_fields")
    @classmethod
    def check_custom_fields(cls, value: dict[str, _t.Any]) -> dict[str, _t.Any]:
        return _custom_fields.validate(value, _CUSTOM_DEFS, max_keys=20, max_bytes=4096)


class ContactUpdate(_pd.BaseModel):
    full_name: str | None = _pd.Field(default=None, max_length=120)
    custom_fields: dict[str, _t.Any] | None = None

    @_pd.field_validator("custom_fields")
    @classmethod
    def check_custom_fields(cls, value: dict[str, _t.Any] | None) -> dict[str, _t.Any] | None:
        if value is None:
            return None
        return _custom_fields.validate(value, _CUSTOM_DEFS, max_keys=20, max_bytes=4096)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("full_name", "custom_fields"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ContactRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    full_name: str
    custom_fields: dict[str, _t.Any]
    created_at: _dt.datetime
    updated_at: _dt.datetime
