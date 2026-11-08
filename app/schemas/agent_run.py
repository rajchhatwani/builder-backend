"""Schemas for builder-agent runs (B3-1). Lease owner and internals are not exposed."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=8000)
    workspace_id: uuid.UUID | None = None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    workspace_id: uuid.UUID | None
    goal: str
    state: str
    phase: str
    budgets: dict[str, Any]
    steps_used: int
    repairs_used: int
    cost_micro_usd: int
    stop_code: str | None
    stop_detail: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    kind: str
    tool_name: str | None
    tool_call_id: str | None
    state: str
    ok: bool
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    model: str | None
    prompt_hash: str | None
    tool_set_hash: str | None
    created_at: datetime


class RunDetail(RunRead):
    steps: list[StepRead]
    steps_total: int
    limit: int
    offset: int
