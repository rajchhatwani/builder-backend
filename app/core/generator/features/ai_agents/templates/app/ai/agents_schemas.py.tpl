"""Request and response models of the agent runtime API (generated, pack ai.agents). Stored prompt text is never returned:
a run shows its goal and proposals, nothing the gateway kept."""

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Autonomy = Literal["suggest", "draft", "auto"]
RunStatus = Literal["completed", "failed", "refused"]
ProposalStatus = Literal[
    "suggested", "acknowledged", "pending_approval", "executed", "failed", "rejected", "rejected_by_policy", "handed_off"
]
Outcome = Literal["success", "failure", "neutral"]


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=4000)
    context: dict[str, Any] | None = None  # at most 8 KB serialized (checked by the service)
    mode: Autonomy | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class HandoffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_role: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=500)


class OutcomeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    note: str | None = Field(default=None, max_length=500)


class ProposalOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    agent: str
    action: str
    kind: str
    risk: str
    args: dict[str, Any]
    allowed_autonomy: Autonomy
    status: ProposalStatus
    reason: str | None
    result: dict[str, Any] | None
    error_code: str | None
    executed_by: str | None
    decided_by: uuid.UUID | None
    decided_at: dt.datetime | None
    note: str | None
    handoff_role: str | None
    outcome: Outcome | None
    outcome_by: uuid.UUID | None
    outcome_at: dt.datetime | None
    created_at: dt.datetime


class RunOut(BaseModel):
    id: uuid.UUID
    agent: str
    goal: str
    mode: Autonomy
    effective_autonomy: Autonomy
    status: RunStatus
    error_code: str | None
    call_id: uuid.UUID | None
    started_by: uuid.UUID | None
    created_at: dt.datetime
    proposals: list[ProposalOut]


class AgentOut(BaseModel):
    name: str
    stage: str
    autonomy: Autonomy
    actions: list[str]
    max_actions_per_run: int
    require_eval: str | None
    eval_ready: bool | None


class ActionOut(BaseModel):
    name: str
    kind: str
    description: str
    risk: str
    max_autonomy: Autonomy
    entity: str | None
    fields: list[str]


class RegistryOut(BaseModel):
    agents: list[AgentOut]
    actions: list[ActionOut]


class AgentStatsOut(BaseModel):
    agent: str
    runs: int
    proposals: int
    executed: int
    rejected: int
    pending: int
    outcome_success: int
    outcome_failure: int
    outcome_neutral: int
    success_rate_bp: int | None


class StatsOut(BaseModel):
    agents: list[AgentStatsOut]
