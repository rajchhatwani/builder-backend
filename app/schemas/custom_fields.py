"""Schemas for per-row custom fields (CP4F2-B)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CustomFieldDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=63)
    type: str = Field(min_length=1, max_length=20)  # string | int | float | bool | date | datetime
    required: bool = False
    max_length: int | None = None
    enum_values: list[str] | None = Field(default=None, max_length=100)


class CustomFieldPatch(BaseModel):
    """Only the attributes sent are changed (send null to clear max_length / enum_values)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=63)
    type: str | None = Field(default=None, min_length=1, max_length=20)
    required: bool | None = None
    max_length: int | None = None
    enum_values: list[str] | None = Field(default=None, max_length=100)


class CustomFieldList(BaseModel):
    entity: str
    enabled: bool
    max_keys: int
    max_bytes: int
    items: list[CustomFieldDef]


class PromoteCheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: list[Any] | None = Field(default=None, max_length=1000)


class PromoteProblemRead(BaseModel):
    code: str
    message: str
    sample_index: int | None = None
    severity: str = "error"


class PromoteCheckResult(BaseModel):
    ok: bool  # nothing blocks the promotion (errors only)
    proven: bool = False  # samples checked, not capped, no error: "Ready" may only be shown when True
    warnings: list[str] = []  # messages of the warning-severity problems
    problems: list[PromoteProblemRead]
    plan_sql: list[str]


class MigrationStepRead(BaseModel):
    kind: str
    safety: str
    reason: str
    sql_hint: str | None = None


class PromoteResult(BaseModel):
    entity: str
    name: str
    op_seq: int
    plan_sql: list[str]
    migration_steps: list[MigrationStepRead]
