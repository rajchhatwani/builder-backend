import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class FixAction(BaseModel):
    action: Literal["open_upgrade", "regenerate", "redeclare_hook", "none"]
    route: str


class ScorecardCheck(BaseModel):
    id: str
    group: str
    status: Literal["pass", "warn", "fail"]
    detail: str
    fix: FixAction


class Scorecard(BaseModel):
    score: int
    passing: bool
    checks: list[ScorecardCheck]


class UpgradeProposalSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    base_generation_id: uuid.UUID
    status: Literal["open", "applied", "dismissed"]
    from_generator_version: str | None
    to_generator_version: str
    block_changes: list[dict[str, Any]]
    file_count: int
    auto_apply_eligible: bool
    created_at: datetime
    decided_at: datetime | None


class UpgradeProposalDetail(UpgradeProposalSummary):
    created_by: uuid.UUID | None
    files: list[dict[str, Any]]
    kept: list[str] = []
    patch_size: int
    sbom_diff: dict[str, Any]
    migrations: list[dict[str, Any]]
    scorecard: dict[str, Any]
