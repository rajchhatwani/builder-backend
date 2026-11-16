"""Request and response models of the document AI API (generated, pack ai.documents). Confidence is integer basis
points (0..10000); anchors are character offsets into the document text."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _no_nul(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("a NUL character cannot be stored")
    return value

DocumentStatus = Literal["extracted", "needs_review", "approved", "rejected"]


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)  # the spec's max_text_chars is checked after parsing
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)

    _nul = field_validator("kind", "title", "content", "idempotency_key")(_no_nul)


class CorrectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(max_length=10_000)

    _nul = field_validator("value")(_no_nul)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledge: list[str] = Field(default_factory=list, max_length=100)  # flagged fields the reviewer accepts as they are


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)

    _nul = field_validator("reason")(_no_nul)


class AnchorOut(BaseModel):
    page: int
    start: int
    end: int
    quote: str


class FieldOut(BaseModel):
    name: str
    value: str | None
    confidence_bp: int
    anchor: AnchorOut | None
    corrected: bool
    original_value: str | None
    review_required: bool


class DocumentOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    status: DocumentStatus
    content: str | None
    call_id: uuid.UUID | None
    fields: list[FieldOut]
    reject_reason: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: dt.datetime | None
    created_by: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime
