"""Pydantic schemas for Invoice (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class InvoiceCreate(_pd.BaseModel):
    invoice_no: str = _pd.Field(max_length=40)
    amount: _decimal.Decimal = _pd.Field(ge=0, max_digits=18, decimal_places=6)
    po_amount: _decimal.Decimal = _pd.Field(ge=0, max_digits=18, decimal_places=6)
    due_date: _dt.date | None = _pd.Field(default=None)
    memo: str | None = _pd.Field(default=None, max_length=200)
    supplier_id: _uuid.UUID


class InvoiceUpdate(_pd.BaseModel):
    invoice_no: str | None = _pd.Field(default=None, max_length=40)
    amount: _decimal.Decimal | None = _pd.Field(default=None, ge=0, max_digits=18, decimal_places=6)
    po_amount: _decimal.Decimal | None = _pd.Field(default=None, ge=0, max_digits=18, decimal_places=6)
    due_date: _dt.date | None = _pd.Field(default=None)
    memo: str | None = _pd.Field(default=None, max_length=200)
    supplier_id: _uuid.UUID | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("invoice_no", "amount", "po_amount", "supplier_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class InvoiceRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    invoice_no: str
    amount: _decimal.Decimal
    po_amount: _decimal.Decimal
    due_date: _dt.date | None
    memo: str | None
    status: _t.Literal['draft', 'submitted', 'pending_approval', 'approved', 'paid', 'rejected']
    supplier_id: _uuid.UUID
    created_at: _dt.datetime
    updated_at: _dt.datetime
