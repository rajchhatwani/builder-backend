import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SpecOpApply(BaseModel):
    """`op_type` must be one of the registry's operations; `payload` is checked against that
    operation's own model."""

    op_type: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)


class SpecRestore(BaseModel):
    to_seq: int = Field(ge=0)


class SpecOpActor(BaseModel):
    kind: str
    user_id: uuid.UUID | None
    email: str | None = None


class SpecOpInverse(BaseModel):
    op_type: str
    payload: dict[str, Any]


class SpecOpRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    seq: int
    op_type: str
    origin: str
    ref_seq: int | None
    actor: SpecOpActor
    payload: dict[str, Any]
    inverse: SpecOpInverse
    spec_hash_before: str
    spec_hash_after: str
    created_at: datetime
