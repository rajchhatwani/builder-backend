"""Request and response models of the booking API (generated). Integers are STRICT: 2.5, "2" and true are refused."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

Mode = Literal["slot", "range", "pool"]
Status = Literal["held", "confirmed", "cancelled", "expired"]


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str = Field(min_length=5, max_length=5)
    end: str = Field(min_length=5, max_length=5)


class ResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    capacity: StrictInt | None = Field(default=None, ge=1, le=100_000)
    schedule: dict[str, list[Window]] | None = None
    active: StrictBool = True


class ResourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: StrictBool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    schedule: dict[str, list[Window]] | None = None


class ResourceOut(BaseModel):
    id: uuid.UUID
    kind: str
    mode: Mode
    name: str
    timezone: str
    slot_minutes: int | None
    schedule: dict[str, list[dict[str, str]]] | None
    capacity: int
    min_minutes: int | None
    max_minutes: int | None
    active: bool
    created_at: dt.datetime


class SlotOut(BaseModel):
    starts_at: dt.datetime
    ends_at: dt.datetime
    free: bool


class AvailabilityOut(BaseModel):
    resource_id: uuid.UUID
    timezone: str
    slot_minutes: int
    slots: list[SlotOut]


class CapacityOut(BaseModel):
    resource_id: uuid.UUID
    capacity: int
    booked: int
    free: int


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: uuid.UUID
    starts_at: dt.datetime
    ends_at: dt.datetime | None = None
    quantity: StrictInt = Field(default=1, ge=1, le=100_000)
    confirm: StrictBool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    customer_ref: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=500)


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=200)


class BookingOut(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    resource_name: str
    kind: str
    mode: Mode
    status: Status
    starts_at: dt.datetime
    ends_at: dt.datetime
    quantity: int
    hold_expires_at: dt.datetime | None
    customer_id: uuid.UUID | None
    customer_ref: str | None
    notes: str | None
    idempotency_key: str | None
    cancel_fee_minor: int | None
    fee_currency: str | None
    cancelled_at: dt.datetime | None
    confirmed_at: dt.datetime | None
    expired_at: dt.datetime | None
    created_at: dt.datetime


class ExpireOut(BaseModel):
    expired: int
