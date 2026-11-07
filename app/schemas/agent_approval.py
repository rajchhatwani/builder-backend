"""Schemas for agent approvals A-E (B3-5)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)
    # Gate A only: approve the plan AFTER the reviewer edited it. Lists of short strings per plan
    # key (see PLAN_KEYS); everything else is dropped. The edited plan, not the agent's, becomes
    # the contract the build phase is checked against.
    plan: dict[str, list[str]] | None = None


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    subject: str
    payload: dict[str, Any]
    risk_flags: list[str]
    state: str  # pending | approved | denied | expired | superseded (expiry applied on read)
    requires_owner: bool = False
    bound_spec_hash: str
    bound_commit: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    expires_at: datetime
    created_at: datetime
