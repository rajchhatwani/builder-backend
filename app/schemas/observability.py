"""Pydantic schemas for the observability (OpenTelemetry) settings of a project.

Shapes and sizes are checked here; whether a value is legal (name pattern, paths, ratio range) is
`validation.validate`'s job, so the dashboard can save work in progress and read every problem.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ObservabilityBody(BaseModel):
    enabled: bool = True
    service_name: str | None = Field(default=None, max_length=80)
    # The 0..1 range is validation's job, so a draft can still be saved.
    sample_ratio: float = Field(default=0.1, ge=-1000, le=1000)
    metrics: bool = True
    db_spans: bool = True
    exclude_paths: list[str] = Field(default_factory=lambda: ["/health", "/ready"], max_length=100)
    extra_redact_keys: list[str] = Field(default_factory=list, max_length=200)
    local_stack: bool = True
    expected_rps: int | None = Field(default=None, ge=-1, le=100_000_000)


class ObservabilityWrite(ObservabilityBody):
    """Body of PUT /projects/{id}/observability. `expected_version` guards against lost updates."""

    expected_version: int | None = Field(default=None, ge=0)


class ObservabilityRead(ObservabilityBody):
    project_id: uuid.UUID
    version: int  # 0 = never saved: these are the defaults
    updated_at: datetime | None = None
    recommended_sample_ratio: float
    default_service_name: str
    # The built-in secret key fragments; the project's own list is added to them.
    redacted_keys: list[str]


class ObservabilityIssues(BaseModel):
    issues: list[dict[str, str]]
