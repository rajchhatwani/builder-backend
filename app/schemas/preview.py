"""Schemas for previews and their admin limits (B3-10). The token is returned once only."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PreviewCreate(BaseModel):
    # Preview a draft workspace's code instead of the project's current spec.
    workspace_id: uuid.UUID | None = None


class PreviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    workspace_id: uuid.UUID | None
    state: str
    spec_hash: str
    url_path: str  # relative: "/previews/{id}/"
    error: str | None = None
    created_at: datetime
    last_request_at: datetime
    expires_at: datetime
    limits: dict[str, object]
    is_preview: bool = True


class PreviewCreated(PreviewRead):
    token: str = Field(description="Shown once. Send it as the X-Preview-Token header.")


class LimitsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_live_per_user: int | None = None
    sleep_after_minutes: int | None = None
    delete_after_days: int | None = None
    cpus: float | None = None
    memory_mb: int | None = None
    db_mb: int | None = None
    rate_per_minute: int | None = None


class PreviewLimitsRead(BaseModel):
    """Platform view: kill switch, the stored defaults (merged over built-ins) and the bounds."""

    kill_switch: bool
    defaults: dict[str, float]
    bounds: dict[str, tuple[float, float]]
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = None


class PreviewLimitsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kill_switch: bool | None = None
    defaults: LimitsBody | None = None


class PreviewOrgLimitsRead(BaseModel):
    organization_id: uuid.UUID
    enabled: bool
    allow_above_default: bool = False
    overrides: dict[str, float]  # only the keys the org overrides
    effective: dict[str, float]
    kill_switch: bool
    note: str | None = None
    updated_at: datetime | None = None


class PreviewOrgLimitsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allow_above_default: bool = False
    overrides: LimitsBody = Field(default_factory=LimitsBody)
    note: str | None = Field(default=None, max_length=500)


class PreviewOrgLimitsRow(BaseModel):
    """One line of the paginated list of all organizations that have an override."""

    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    enabled: bool
    allow_above_default: bool
    overrides: dict[str, float]
    note: str | None = None
    updated_at: datetime | None = None


class PreviewUsageRead(BaseModel):
    live: int  # starting + running + stopping + sleeping
    running: int
    by_state: dict[str, int]
    orgs_with_overrides: int
    kill_switch: bool
