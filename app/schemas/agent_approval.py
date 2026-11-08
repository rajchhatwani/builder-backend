"""Schemas for agent approvals A-E (B3-5)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# S1-011: the edited plan is bounded by the schema (the same limits clean_plan applies afterwards),
# so an oversized body is a 422 before any work is done. At most 8 keys.
_PlanKey = Annotated[str, StringConstraints(max_length=40)]  # unknown keys are dropped by clean_plan
_PlanItem = Annotated[str, StringConstraints(max_length=120)]
_PlanList = Annotated[list[_PlanItem], Field(max_length=100)]


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)
    # Gate A only: approve the plan AFTER the reviewer edited it. Lists of short strings per plan
    # key (see PLAN_KEYS); everything else is dropped. The edited plan, not the agent's, becomes
    # the contract the build phase is checked against.
    plan: Annotated[dict[_PlanKey, _PlanList], Field(max_length=8)] | None = None
    # S3-004/S3-005: hashes of what the reviewer saw (ApprovalRead.payload_hash / bound_spec_hash).
    # Required to approve an approval that has a payload_hash; a mismatch is 409 approval_changed.
    expected_payload_hash: str | None = Field(default=None, max_length=64)
    expected_spec_hash: str | None = Field(default=None, max_length=128)


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
    payload_hash: str | None = None
    bound_spec_hash: str
    bound_commit: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    expires_at: datetime
    created_at: datetime
