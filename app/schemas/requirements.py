"""Schemas for the requirements map (B3-6)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal[
    "actor", "entity", "workflow", "rule", "integration", "compliance", "nonfunctional", "out_of_scope"
]
ItemStatus = Literal["open", "covered", "out_of_scope"]


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: Kind
    text: str
    subject: str | None
    value: str | None
    source_doc: str | None
    source_page: int | None
    source_section: str | None
    status: ItemStatus
    covered_by: str | None


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    assumption: str
    answer: str | None
    state: Literal["open", "answered", "assumed"]


class SourceRead(BaseModel):
    name: str
    kind: str
    pages: int
    chunks: int
    chars: int


class Coverage(BaseModel):
    total: int
    open: int
    covered: int
    out_of_scope: int
    percent_covered: int
    open_questions: int


class PhaseRead(BaseModel):
    number: int
    name: str
    kinds: list[str]
    items: int


class RequirementsRead(BaseModel):
    id: uuid.UUID | None
    project_id: uuid.UUID
    status: str
    items: list[ItemRead]
    questions: list[QuestionRead]
    sources: list[SourceRead]
    coverage: Coverage
    phases: list[PhaseRead]
    created_at: datetime | None
    updated_at: datetime | None


class QuestionAnswer(BaseModel):
    answer: str | None = Field(default=None, max_length=2000)
    accept_assumption: bool = False

    @model_validator(mode="after")
    def _one_of(self) -> "QuestionAnswer":
        has = bool(self.answer and self.answer.strip())
        if has == self.accept_assumption:
            raise ValueError("send either a non-empty answer or accept_assumption=true")
        return self


class ItemUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=600)
    status: ItemStatus | None = None
    covered_by: str | None = Field(default=None, max_length=200)


class StartRun(BaseModel):
    accept_assumptions: bool = False
    phase: int = Field(default=1, ge=1, le=10)
    workspace_id: uuid.UUID | None = None
