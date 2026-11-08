"""Pydantic schemas for the cloud deployment settings of a project.

Shapes and sizes are checked here; whether a value is legal (cloud, region, size pairs, supported
features) is `validation.validate`'s job, so the dashboard can save a draft and read every problem.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DeployEnvironmentBody(BaseModel):
    name: str = Field(max_length=40)
    profile: str = Field(default="small", max_length=10)
    min_instances: int | None = Field(default=None, ge=-1, le=100_000)
    max_instances: int | None = Field(default=None, ge=-1, le=100_000)
    cpu: int | None = Field(default=None, ge=0, le=1_000_000)
    memory: int | None = Field(default=None, ge=0, le=10_000_000)
    db_storage_gb: int | None = Field(default=None, ge=0, le=100_000_000)
    db_high_availability: bool | None = None
    deletion_protection: bool | None = None


class DeploymentBody(BaseModel):
    enabled: bool = True
    cloud: str = Field(default="aws", max_length=10)
    region: str = Field(default="", max_length=60)
    github_repo: str = Field(default="", max_length=200)
    environments: list[DeployEnvironmentBody] = Field(default_factory=list, max_length=50)


class DeploymentWrite(DeploymentBody):
    """Body of PUT /projects/{id}/deployment. `expected_version` guards against lost updates."""

    expected_version: int | None = Field(default=None, ge=0)


class DeploymentRead(DeploymentBody):
    project_id: uuid.UUID
    version: int  # 0 = never saved: these are the defaults
    updated_at: datetime | None = None


class DeploymentIssues(BaseModel):
    issues: list[dict[str, str]]


class ResolvedEnvironment(BaseModel):
    name: str
    profile: str
    cpu: int
    memory: int
    min_instances: int
    max_instances: int
    db_class: str
    db_storage_gb: int
    db_high_availability: bool
    deletion_protection: bool
    tfvars: str


class DeploymentPlan(BaseModel):
    """What the settings turn into: concrete numbers and the tfvars files, for a live preview."""

    cloud: str
    region: str
    environments: list[ResolvedEnvironment]
    valid_sizes: list[tuple[int, int]]
    notes: list[str]
