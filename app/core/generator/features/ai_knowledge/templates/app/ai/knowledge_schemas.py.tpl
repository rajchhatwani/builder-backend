"""Request and response models of the knowledge library API (generated, pack ai.knowledge)."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _no_nul(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("a NUL character cannot be stored")
    return value


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=5_000_000)  # the spec's max_text_chars is checked after parsing
    allowed_roles: list[str] | None = Field(default=None, max_length=50)
    owner_only: bool | None = None

    _nul = field_validator("title", "text")(_no_nul)


class SourceOut(BaseModel):
    id: uuid.UUID
    title: str
    allowed_roles: list[str]
    owner_only: bool
    owner_id: uuid.UUID
    chunk_count: int
    created_at: dt.datetime


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)

    _nul = field_validator("query")(_no_nul)


class HitOut(BaseModel):
    source_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    text: str
    position: int
    score_bp: int


class SearchOut(BaseModel):
    hits: list[HitOut]


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=4, ge=1, le=10)

    _nul = field_validator("question")(_no_nul)


class CitationOut(BaseModel):
    source_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    quote: str
    score_bp: int


class AskOut(BaseModel):
    answer: str
    grounded: bool
    citations: list[CitationOut]
    call_id: uuid.UUID | None
