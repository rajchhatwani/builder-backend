"""Request and response models of the reconciliation API (generated). Amounts are STRICT integers."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.money.reconciliation.config import MAX_LINES


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=128)
    date: dt.date
    # same sign as the ledger account's entries: positive = debit side of the account
    amount_minor: StrictInt = Field(ge=-(2**53 - 1), le=2**53 - 1)
    currency: str = Field(min_length=3, max_length=3)
    reference: str | None = Field(default=None, max_length=128)


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)
    account_id: uuid.UUID
    name: str | None = Field(default=None, max_length=200)
    period_start: dt.date | None = None
    period_end: dt.date | None = None
    lines: list[LineIn] = Field(min_length=1, max_length=MAX_LINES)


class LinesAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[LineIn] = Field(min_length=1, max_length=MAX_LINES)


class ManualMatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: uuid.UUID
    entry_id: uuid.UUID


class SummaryOut(BaseModel):
    """All amounts are integer minor units. difference_minor = statement total - ledger total of the entries
    considered = matched_diff_minor + unmatched_lines_minor - unmatched_entries_minor."""

    currency: str
    line_count: int
    matched_count: int
    unmatched_line_count: int
    unmatched_entry_count: int
    statement_total_minor: int
    matched_lines_minor: int
    matched_entries_minor: int
    matched_diff_minor: int
    unmatched_lines_minor: int
    unmatched_entries_minor: int
    difference_minor: int


class RunOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    currency: str
    name: str | None
    period_start: dt.date | None
    period_end: dt.date | None
    status: str
    line_count: int
    matched_count: int
    created_at: dt.datetime
    closed_at: dt.datetime | None
    summary: SummaryOut | None


class LineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    external_id: str
    date: dt.date
    amount_minor: int
    currency: str
    reference: str | None


class EntryRefOut(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    date: dt.date
    amount_minor: int
    reference: str | None
    description: str | None


class MatchOut(BaseModel):
    id: uuid.UUID
    line_id: uuid.UUID
    entry_id: uuid.UUID
    method: str
    diff_minor: int
    matched_at: dt.datetime


class MatchedPairOut(BaseModel):
    match: MatchOut
    line: LineOut
    entry: EntryRefOut


class ResultsOut(BaseModel):
    run: RunOut
    matched: list[MatchedPairOut]
    unmatched_lines: list[LineOut]
    unmatched_entries: list[EntryRefOut]
    entries_truncated: bool
    summary: SummaryOut


class LinesAddedOut(BaseModel):
    added: int
    skipped: int
    line_count: int


class AutoMatchOut(BaseModel):
    new_matches: int
    matched_count: int
    unmatched_line_count: int
    entries_truncated: bool = False
