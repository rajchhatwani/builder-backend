"""Input and output models of the custom hooks (generated from the spec: change them in the
builder, never here)."""

import uuid as _uuid

from pydantic import BaseModel, ConfigDict

__all__ = ["PeekInput", "PeekResult"]


class PeekInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _uuid.UUID
    title: str


class PeekResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seen: bool
