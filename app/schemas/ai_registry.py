"""Schemas for the AI cost endpoints and the registry (B3-7, B3-8)."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

_HASH = re.compile(r"^[0-9a-f]{64}$")


class AiLedgerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    run_id: uuid.UUID | None
    model: str
    task_class: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_micro_usd: int
    created_at: datetime


class AiCostSummary(BaseModel):
    month_start: datetime
    month_cost_micro_usd: int
    total_cost_micro_usd: int
    monthly_budget_micro_usd: int | None
    items: list[AiLedgerRead]
    total: int
    limit: int
    offset: int


class AiSettingsRead(BaseModel):
    has_api_key: bool
    api_key_hint: str | None
    monthly_budget_micro_usd: int | None


class AiSettingsWrite(BaseModel):
    api_key: SecretStr | None = Field(default=None, min_length=8, max_length=300)
    clear_api_key: bool = False
    monthly_budget_micro_usd: int | None = Field(default=None, ge=0)
    clear_budget: bool = False


# -- registry --------------------------------------------------------------------------------


def _check_hash(v: str) -> str:
    v = v.lower()
    if not _HASH.match(v):
        raise ValueError("must be a 64-character hex SHA-256")
    return v


class BlockVersionWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    content_hash: str

    _h = field_validator("content_hash")(_check_hash)


class BlockVersionRead(BlockVersionWrite):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime


class HookEntryWrite(BaseModel):
    hook_name: str = Field(min_length=1, max_length=100)
    content_hash: str
    author: str = Field(min_length=1, max_length=200)

    _h = field_validator("content_hash")(_check_hash)


class HookEntryRead(HookEntryWrite):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    approved_by: uuid.UUID | None
    created_at: datetime


class DepLockWrite(BaseModel):
    package: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    hash: str = Field(min_length=1, max_length=200)


class DepLockRead(DepLockWrite):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime


class RegistryProjectRead(BaseModel):
    project_id: uuid.UUID
    name: str
    slug: str
    spec_version: int
    block_versions: int
    hooks: int
    hooks_unapproved: int
    dependencies: int


class AiPlatformBudgetRead(BaseModel):
    cap_micro_usd: int | None
    spent_micro_usd: int
    reserved_micro_usd: int
    remaining_micro_usd: int | None
