"""Input and output models of the custom hooks (generated from the spec: change them in the
builder, never here)."""

from pydantic import BaseModel, ConfigDict

__all__ = ["RequestInput", "RequestResult"]


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    days: int
    reason: str | None = None


class RequestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    message: str | None = None
