"""Request and response models of the invoicing API (generated). Amounts and quantities are STRICT integers:
10.5, "10" and true are refused with 422, never rounded."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.money.invoicing.config import MAX_AMOUNT_MINOR, MAX_LINES

Kind = Literal["receivable", "payable"]


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)
    quantity: StrictInt = Field(ge=1, le=1_000_000_000)
    unit_price_minor: StrictInt = Field(ge=0, le=MAX_AMOUNT_MINOR)
    tax_rate: str | None = Field(default=None, min_length=1, max_length=32)


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    counterparty: str = Field(min_length=1, max_length=200)
    counterparty_ref: str | None = Field(default=None, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    issue_date: dt.date | None = None
    due_date: dt.date | None = None
    notes: str | None = Field(default=None, max_length=500)
    lines: list[LineIn] = Field(min_length=1, max_length=MAX_LINES)


class InvoiceUpdate(BaseModel):
    """Draft invoices only. Fields that are left out stay; `lines` replaces all lines."""

    model_config = ConfigDict(extra="forbid")

    counterparty: str | None = Field(default=None, min_length=1, max_length=200)
    counterparty_ref: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    issue_date: dt.date | None = None
    due_date: dt.date | None = None
    notes: str | None = Field(default=None, max_length=500)
    lines: list[LineIn] | None = Field(default=None, min_length=1, max_length=MAX_LINES)


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)
    amount_minor: StrictInt = Field(ge=1, le=MAX_AMOUNT_MINOR)
    paid_on: dt.date | None = None
    reference: str | None = Field(default=None, max_length=128)


class VoidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class LineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    description: str
    quantity: int
    unit_price_minor: int
    tax_rate: str | None
    net_minor: int
    tax_minor: int
    gross_minor: int


class PaymentOut(BaseModel):
    id: uuid.UUID
    amount_minor: int
    paid_on: dt.date
    reference: str | None
    ledger_transaction_id: uuid.UUID
    created_at: dt.datetime


class InvoiceOut(BaseModel):
    id: uuid.UUID
    kind: Kind
    number: str | None
    status: str
    counterparty: str
    counterparty_ref: str | None
    currency: str
    exponent: int
    issue_date: dt.date | None
    due_date: dt.date | None
    notes: str | None
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    paid_minor: int
    outstanding_minor: int
    issue_transaction_id: uuid.UUID | None
    void_transaction_id: uuid.UUID | None
    created_at: dt.datetime
    issued_at: dt.datetime | None
    voided_at: dt.datetime | None
    lines: list[LineOut]
    payments: list[PaymentOut]


class AgingBucketOut(BaseModel):
    label: str
    from_days: int
    to_days: int | None
    amount_minor: int
    count: int


class AgingCurrencyOut(BaseModel):
    currency: str
    current_minor: int
    current_count: int
    buckets: list[AgingBucketOut]
    total_minor: int
    count: int


class AgingOut(BaseModel):
    kind: Kind
    as_of: dt.date
    bucket_days: list[int]
    currencies: list[AgingCurrencyOut]


class PayoutRunIn(BaseModel):
    """Run a payout. Irreversible. `seller` is an operator-chosen label, not checked against the invoice counterparty:
    a non-empty string without spaces or control characters (the pattern rejects them, also a trailing newline)."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)
    invoice_id: uuid.UUID
    seller: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")


class PayoutOut(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    seller: str
    currency: str
    gross_minor: int
    commission_bp: int
    commission_minor: int
    seller_minor: int
    split_transaction_id: uuid.UUID
    payout_transaction_id: uuid.UUID | None
    created_at: dt.datetime


class PayoutTotalOut(BaseModel):
    seller: str
    currency: str
    count: int
    gross_minor: int
    commission_minor: int
    seller_minor: int
