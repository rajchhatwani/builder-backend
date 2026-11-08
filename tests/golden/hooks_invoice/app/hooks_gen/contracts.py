"""Input and output models of the custom hooks (generated from the spec: change them in the
builder, never here)."""

import decimal as _decimal
import uuid as _uuid

from pydantic import BaseModel, ConfigDict

__all__ = ["MatchInput", "MatchResult", "NotifyInput", "NotifyResult"]


class MatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invoice_no: str
    amount: _decimal.Decimal
    po_amount: _decimal.Decimal


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason: str | None = None


class NotifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _uuid.UUID
    invoice_no: str
    status: str
    amount: _decimal.Decimal


class NotifyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sent: bool
