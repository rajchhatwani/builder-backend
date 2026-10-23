"""Request and response models of the payment routes (generated).

Responses carry our own ids, statuses and amounts only. Provider references, customer details and
anything else the provider knows stay out of the API.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    """The amount is deliberately absent: it is read from the item on the server."""

    model_config = ConfigDict(extra="forbid")

    payable_id: uuid.UUID
    success_url: str | None = Field(default=None, max_length=2000)
    cancel_url: str | None = Field(default=None, max_length=2000)


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payable_id: uuid.UUID
    status: str
    amount_minor: int
    currency: str
    refunded_minor: int
    livemode: bool
    # Only while the payer still has to pay; afterwards the link is of no use.
    checkout_url: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int | None = Field(default=None, ge=1, le=9_000_000_000_000_000)
    reason: str = "requested_by_customer"


class RefundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    amount_minor: int
    currency: str
    status: str
    reason: str
    source: str
    requested_by_id: uuid.UUID | None
    approved_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DisputeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    status: str
    reason: str | None
    amount_minor: int
    currency: str
    evidence_due_by: datetime | None
    opened_at: datetime | None
    closed_at: datetime | None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    status: str
    attempts: int
    max_attempts: int
    last_error_code: str | None
    run_at: datetime
    updated_at: datetime


class AuditVerification(BaseModel):
    intact: bool
    first_bad_sequence: int | None


class OpsStatus(BaseModel):
    queue: dict[str, Any]
    events_failed: int
    events_unprocessed: int
