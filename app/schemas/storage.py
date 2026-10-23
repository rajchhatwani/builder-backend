"""Pydantic schemas for a project's storage settings (builder API layer).

Shapes and ranges are checked here; whether a combination is *legal* (bucket naming, role names,
file fields) is `validation.validate`'s job, so the dashboard can save work in progress and see
every problem in one report. No field here can hold a bucket credential: they are environment
variables of the generated project.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DownloadMode, StorageBackend


class StorageRoles(BaseModel):
    upload: list[str] = Field(default_factory=list, max_length=50)
    share: list[str] = Field(default_factory=list, max_length=50)
    read: list[str] = Field(default_factory=list, max_length=50)
    read_all: list[str] = Field(default_factory=list, max_length=50)
    delete: list[str] = Field(default_factory=list, max_length=50)
    delete_all: list[str] = Field(default_factory=list, max_length=50)
    operate: list[str] = Field(default_factory=list, max_length=50)


class StorageSecurity(BaseModel):
    audit_retention_days: int = Field(default=2555, ge=1, le=1_000_000)
    audit_ip: bool = True
    rescan_after_days: int = Field(default=30, ge=1, le=100_000)
    scan_timeout_seconds: int = Field(default=120, ge=1, le=100_000)


class StorageConfigWrite(BaseModel):
    """Body of PUT /projects/{id}/storage."""

    backend: StorageBackend = StorageBackend.s3
    bucket: str = Field(default="", max_length=63)
    region: str | None = Field(default=None, max_length=32)
    key_prefix: str = Field(default="uploads", max_length=100)
    allowed_types: list[str] = Field(default_factory=list, max_length=60)
    max_file_mb: int = Field(default=25, ge=1, le=100_000)
    user_quota_mb: int | None = Field(default=None, ge=1, le=100_000_000)
    uploads_per_hour: int = Field(default=60, ge=1, le=1_000_000)
    download_mode: DownloadMode = DownloadMode.proxy
    allow_inline_images: bool = False
    roles: StorageRoles = Field(default_factory=StorageRoles)
    security: StorageSecurity = Field(default_factory=StorageSecurity)


class StorageConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    enabled: bool
    backend: StorageBackend
    bucket: str
    region: str | None
    key_prefix: str
    allowed_types: list[str]
    max_file_mb: int
    user_quota_mb: int | None
    uploads_per_hour: int
    download_mode: DownloadMode
    allow_inline_images: bool
    roles: StorageRoles
    security: StorageSecurity
    created_at: datetime
    updated_at: datetime


class StorageSwitchRequest(BaseModel):
    """Body of POST .../storage/enable and .../storage/disable: both change what the next
    generated project contains, so the caller must say so."""

    confirm: bool = False


class StorageImpact(BaseModel):
    action: str  # "enable" | "disable"
    enabled: bool  # the current state
    can_proceed: bool
    blockers: list[str]
    warnings: list[str]


class StorageIssues(BaseModel):
    """Validation issues under `storage` (and file fields), without side effects."""

    issues: list[dict[str, str]]
