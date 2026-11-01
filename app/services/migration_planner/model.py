# ruff: noqa: E501
"""Plan data model: immutable, JSON-stable. Pure data, no I/O."""

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MigrationPlanError(ValueError):
    """Malformed input or renames: the planner fails closed instead of guessing."""


class Safety(StrEnum):
    safe = "safe"
    backfill = "backfill"
    destructive = "destructive"


class StepKind(StrEnum):
    create_table = "create_table"
    rename_table = "rename_table"
    rename_column = "rename_column"
    add_column = "add_column"
    add_tenant_id = "add_tenant_id"
    widen_type = "widen_type"
    convert_type = "convert_type"
    relax_not_null = "relax_not_null"
    add_enum_value = "add_enum_value"
    change_default = "change_default"
    add_index = "add_index"
    drop_index = "drop_index"
    add_unique = "add_unique"
    drop_unique = "drop_unique"
    add_fk = "add_fk"
    drop_fk = "drop_fk"
    alter_fk = "alter_fk"
    set_not_null = "set_not_null"
    drop_column = "drop_column"
    drop_tenant_id = "drop_tenant_id"
    drop_table = "drop_table"
    narrow_type = "narrow_type"
    shorten_length = "shorten_length"
    drop_enum_value = "drop_enum_value"
    change_type = "change_type"


# Dependency order: tables first, then columns, then data fixes, then constraints, destructive last.
PHASES: dict[str, int] = {
    "create": 0,
    "rename": 1,
    "additive": 2,
    "backfill": 3,
    "constrain": 4,
    "destructive": 5,
}


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    phase: int
    kind: StepKind
    entity: str
    table: str
    field: str | None = None
    safety: Safety
    reason: str
    suggested_action: str | None = None
    backfill_strategy: str | None = None  # backfill steps: what to run BEFORE the constraint
    sql_hint: str | None = None  # PostgreSQL, advisory: the generated Alembic revision is authoritative
    note: str | None = None


class MigrationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: list[PlanStep] = Field(default_factory=list)
    ignored_sections: list[str] = Field(default_factory=list)  # changed, but no schema change

    @property
    def is_empty(self) -> bool:
        return not self.steps

    @property
    def requires_confirmation(self) -> bool:
        return any(s.safety == Safety.destructive for s in self.steps)

    @property
    def requires_backfill(self) -> bool:
        return any(s.safety == Safety.backfill for s in self.steps)

    @property
    def highest_safety(self) -> Safety | None:
        for level in (Safety.destructive, Safety.backfill, Safety.safe):
            if any(s.safety == level for s in self.steps):
                return level
        return None

    def apply_allowed(self, allow_destructive: bool = False) -> bool:
        """False when the plan holds a destructive step and the caller did not opt in."""
        return allow_destructive or not self.requires_confirmation

    def blocked_steps(self, allow_destructive: bool = False) -> list[PlanStep]:
        if allow_destructive:
            return []
        return [s for s in self.steps if s.safety == Safety.destructive]

    def to_json(self) -> str:
        """Byte-stable: same plan -> identical string."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.model_dump(mode="json") for s in self.steps],
            "ignored_sections": list(self.ignored_sections),
            "requires_confirmation": self.requires_confirmation,
            "requires_backfill": self.requires_backfill,
            "highest_safety": self.highest_safety.value if self.highest_safety else None,
        }
