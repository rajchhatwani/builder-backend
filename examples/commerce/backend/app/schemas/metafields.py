"""Pydantic schemas for Metafield (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class MetafieldCreate(_pd.BaseModel):
    owner_type: str = _pd.Field(max_length=40)
    owner_id: _uuid.UUID
    namespace: str = _pd.Field(max_length=60)
    key: str = _pd.Field(max_length=60)
    value_type: _t.Literal['string', 'integer', 'decimal', 'boolean', 'json', 'date']
    value: _t.Any


class MetafieldUpdate(_pd.BaseModel):
    owner_type: str | None = _pd.Field(default=None, max_length=40)
    owner_id: _uuid.UUID | None = _pd.Field(default=None)
    namespace: str | None = _pd.Field(default=None, max_length=60)
    key: str | None = _pd.Field(default=None, max_length=60)
    value_type: _t.Literal['string', 'integer', 'decimal', 'boolean', 'json', 'date'] | None = _pd.Field(default=None)
    value: _t.Any = _pd.Field(default=None)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("owner_type", "owner_id", "namespace", "key", "value_type", "value"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class MetafieldRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    owner_type: str
    owner_id: _uuid.UUID
    namespace: str
    key: str
    value_type: _t.Literal['string', 'integer', 'decimal', 'boolean', 'json', 'date']
    value: _t.Any
    created_at: _dt.datetime
    updated_at: _dt.datetime
