import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RenameHint(BaseModel):
    """A declared rename. Entity rename: `{from, to}`. Field rename: `{entity, from, to}`."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: str | None = Field(default=None, pattern="^(entity|field)$")
    entity: str | None = None
    from_: str = Field(alias="from", min_length=1, max_length=200)
    to: str = Field(min_length=1, max_length=200)


class MigrationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    renames: list[RenameHint] = Field(default_factory=list, max_length=200)
    against_generation_id: uuid.UUID | None = None


class MigrationPlanStepOut(BaseModel):
    seq: int
    phase: int
    kind: str
    entity: str
    table: str
    field: str | None
    safety: str
    reason: str
    suggested_action: str | None
    backfill_strategy: str | None
    sql_hint: str | None
    note: str | None


class MigrationPlanBody(BaseModel):
    steps: list[MigrationPlanStepOut]
    ignored_sections: list[str]
    requires_confirmation: bool
    requires_backfill: bool
    highest_safety: str | None


class MigrationPlanResponse(BaseModel):
    plan: MigrationPlanBody
    text: str
    old_spec_hash: str | None
    new_spec_hash: str
    against_generation_id: uuid.UUID | None
    first_generation: bool
    old_snapshot_unusable: bool = False
    allow_destructive_required: bool


def plan_response_dict(resp: MigrationPlanResponse) -> dict[str, Any]:
    return resp.model_dump(mode="json")
