"""Input and output models of the custom hooks (generated from the spec: change them in the
builder, never here)."""

import uuid as _uuid

from pydantic import BaseModel, ConfigDict

__all__ = ["AnnounceInput", "AnnounceResult"]


class AnnounceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _uuid.UUID
    reference: str


class AnnounceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sent: bool
