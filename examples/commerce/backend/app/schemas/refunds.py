"""Pydantic schemas for Refund (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class RefundCreate(_pd.BaseModel):
    amount: _decimal.Decimal = _pd.Field(default=_decimal.Decimal('0'), ge=0)
    reason: str | None = _pd.Field(default=None, max_length=255)
    restock: bool | None = _pd.Field(default=False)
    note: str | None = _pd.Field(default=None)
    order_id: _uuid.UUID


class RefundUpdate(_pd.BaseModel):
    amount: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    reason: str | None = _pd.Field(default=None, max_length=255)
    restock: bool | None = _pd.Field(default=None)
    note: str | None = _pd.Field(default=None)
    order_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("amount", "order_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class RefundRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    amount: _decimal.Decimal
    reason: str | None
    restock: bool | None
    note: str | None
    order_id: _uuid.UUID
    lines: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("lines", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
