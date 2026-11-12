"""Request and response models of the ledger API (generated). Amounts are STRICT integers: 10.0, "10" and
true are refused with 422, never rounded."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.money.ledger.config import MAX_AMOUNT_MINOR, MAX_ENTRIES

AccountKind = Literal["asset", "liability", "equity", "income", "expense"]


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    name: str = Field(min_length=1, max_length=200)
    kind: AccountKind
    currency: str = Field(min_length=3, max_length=3)


class AccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: AccountKind
    currency: str
    exponent: int
    created_at: dt.datetime


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    # signed: positive = debit, negative = credit
    amount_minor: StrictInt = Field(ge=-MAX_AMOUNT_MINOR, le=MAX_AMOUNT_MINOR)


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=128)
    entries: list[EntryIn] = Field(min_length=2, max_length=MAX_ENTRIES)


class ReverseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)


class EntryOut(BaseModel):
    id: uuid.UUID
    line_no: int
    account_id: uuid.UUID
    currency: str
    amount_minor: int
    direction: Literal["debit", "credit"]


class TransactionOut(BaseModel):
    id: uuid.UUID
    idempotency_key: str
    description: str | None
    reference: str | None
    reverses_id: uuid.UUID | None
    reversed_by_id: uuid.UUID | None
    posted_at: dt.datetime
    posted_by: uuid.UUID | None
    entries: list[EntryOut]


class AccountEntryOut(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    line_no: int
    currency: str
    amount_minor: int
    direction: Literal["debit", "credit"]
    posted_at: dt.datetime
    description: str | None
    reverses_id: uuid.UUID | None


class BalanceOut(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    currency: str
    exponent: int
    balance_minor: int
    debit_total_minor: int
    credit_total_minor: int


class CurrencyTotalOut(BaseModel):
    currency: str
    sum_minor: int


class BalancesOut(BaseModel):
    items: list[BalanceOut]
    totals: list[CurrencyTotalOut]
    truncated: bool = False  # True when more accounts exist than `items` lists; `totals` always cover all
