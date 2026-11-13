"""Request and response models of the AI gateway API (generated). Integers are STRICT: 2.5, "2" and true are refused;
amounts are integer micro-USD (1 USD = 1_000_000)."""

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

CallStatus = Literal["reserved", "ok", "error"]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=40)
    messages: list[Message] = Field(min_length=1, max_length=50)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    max_output_tokens: StrictInt | None = Field(default=None, ge=1, le=100_000)
    response_format: Literal["text", "json"] = "text"


class CompleteOut(BaseModel):
    call_id: uuid.UUID
    stage: str
    provider: str
    model: str
    status: CallStatus
    output_text: str | None
    output_json: Any | None
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    fallback_used: bool
    replayed: bool
    created_at: dt.datetime


class CallOut(BaseModel):
    id: uuid.UUID
    caller_id: uuid.UUID | None
    stage: str
    provider: str
    model: str
    status: CallStatus
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    reserved_micro_usd: int
    prompt_hash: str
    error_code: str | None
    fallback_used: bool
    idempotency_key: str | None
    created_at: dt.datetime
    finished_at: dt.datetime | None


class UsageOut(BaseModel):
    period: str
    period_start: dt.date
    limit_micro_usd: int
    spent_micro_usd: int
    reserved_micro_usd: int
    remaining_micro_usd: int
    calls_ok: int
    calls_error: int
    input_tokens: int
    output_tokens: int
    zero_retention: bool
    region: str
