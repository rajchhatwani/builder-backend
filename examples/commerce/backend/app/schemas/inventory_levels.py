"""Pydantic schemas for InventoryLevel (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class InventoryLevelCreate(_pd.BaseModel):
    available: int = _pd.Field(default=0)
    on_hand: int | None = _pd.Field(default=0)
    committed: int | None = _pd.Field(default=0, ge=0)
    incoming: int | None = _pd.Field(default=0, ge=0)
    location_id: _uuid.UUID
    variant_id: _uuid.UUID


class InventoryLevelUpdate(_pd.BaseModel):
    available: int | None = _pd.Field(default=None)
    on_hand: int | None = _pd.Field(default=None)
    committed: int | None = _pd.Field(default=None, ge=0)
    incoming: int | None = _pd.Field(default=None, ge=0)
    location_id: _uuid.UUID | None = None
    variant_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("available", "location_id", "variant_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class InventoryLevelRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    available: int
    on_hand: int | None
    committed: int | None
    incoming: int | None
    location_id: _uuid.UUID
    variant_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
