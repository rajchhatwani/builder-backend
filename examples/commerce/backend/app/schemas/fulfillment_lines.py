"""Pydantic schemas for FulfillmentLine (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class FulfillmentLineCreate(_pd.BaseModel):
    quantity: int = _pd.Field(ge=1)
    fulfillment_id: _uuid.UUID
    order_line_id: _uuid.UUID


class FulfillmentLineUpdate(_pd.BaseModel):
    quantity: int | None = _pd.Field(default=None, ge=1)
    fulfillment_id: _uuid.UUID | None = None
    order_line_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("quantity", "fulfillment_id", "order_line_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class FulfillmentLineRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    quantity: int
    fulfillment_id: _uuid.UUID
    order_line_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
