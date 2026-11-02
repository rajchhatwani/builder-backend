"""Schemas for the dependency policy endpoints (B3-9)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.dependency_policy_service import normalize_name, validate_hash, validate_version


class DependencyRequestWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=3, max_length=2000)
    hashes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("package")
    @classmethod
    def _package(cls, v: str) -> str:
        return normalize_name(v)

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        return validate_version(v)

    @field_validator("hashes")
    @classmethod
    def _hashes(cls, v: list[str]) -> list[str]:
        return [validate_hash(h) for h in v]


class DependencyDecision(BaseModel):
    """Approve must echo what was reviewed; a changed request is refused (409)."""

    model_config = ConfigDict(extra="forbid")
    package: str | None = Field(default=None, max_length=100)
    version: str | None = Field(default=None, max_length=50)
    hashes: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=500)


class DependencyRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    package: str
    version: str
    reason: str
    hashes: list[str]
    status: str
    requested_by: uuid.UUID | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    expires_at: datetime | None
    revoked_by: uuid.UUID | None
    revoked_at: datetime | None
    created_at: datetime


class ApprovedPin(BaseModel):
    package: str
    version: str
    hashes: list[str]
    expires_at: datetime | None


class DependencyPolicyRead(BaseModel):
    curated_sets: dict[str, dict[str, str]]
    allow_list: list[str]
    approved: list[ApprovedPin]
    pending_requests: int
