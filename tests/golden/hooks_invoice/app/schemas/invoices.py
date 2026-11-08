"""Pydantic schemas for Invoice (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class InvoiceCreate(_pd.BaseModel):
    invoice_no: str = _pd.Field(max_length=40)
    amount: _decimal.Decimal = _pd.Field(max_digits=18, decimal_places=6)
    po_amount: _decimal.Decimal = _pd.Field(max_digits=18, decimal_places=6)


class InvoiceUpdate(_pd.BaseModel):
    invoice_no: str | None = _pd.Field(default=None, max_length=40)
    amount: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)
    po_amount: _decimal.Decimal | None = _pd.Field(default=None, max_digits=18, decimal_places=6)

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("invoice_no", "amount", "po_amount"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class InvoiceRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    invoice_no: str
    amount: _decimal.Decimal
    po_amount: _decimal.Decimal
    status: _t.Literal['draft', 'submitted', 'pending_approval', 'approved', 'paid', 'rejected']
    created_at: _dt.datetime
    updated_at: _dt.datetime
