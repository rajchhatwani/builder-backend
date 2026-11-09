"""Schemas for the data import (B4-1)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportCounts(BaseModel):
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicate: int = 0
    fixed: int = 0


class RowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    row_no: int
    raw: dict[str, Any]
    record: dict[str, Any] | None
    status: str
    errors: list[dict[str, Any]]


class RowPage(BaseModel):
    items: list[RowRead]
    total: int
    limit: int
    offset: int


class ImportPreview(BaseModel):
    batch_id: uuid.UUID
    entity: str
    status: str
    headers: list[str]
    mapping: dict[str, str]
    suggested_mapping: dict[str, str]
    counts: ImportCounts
    sample: list[RowRead]
    rejected: list[RowRead]


class BatchRead(BaseModel):
    id: uuid.UUID
    entity: str
    filename: str
    content_sha256: str
    status: str
    mapping: dict[str, str]
    counts: dict[str, Any]
    created_at: datetime
    committed_at: datetime | None


class BatchPage(BaseModel):
    items: list[BatchRead]
    total: int
    limit: int
    offset: int


class MappingBody(BaseModel):
    mapping: dict[str, str | None]


class RowFix(BaseModel):
    values: dict[str, Any] = Field(max_length=100)


class CommitResult(BaseModel):
    batch_id: uuid.UUID
    status: str
    created: int
    duplicate: int
    rejected: int


class RecordRead(BaseModel):
    id: uuid.UUID
    entity: str
    data: dict[str, Any]
    batch_id: uuid.UUID | None
    created_at: datetime


class RecordPage(BaseModel):
    items: list[RecordRead]
    total: int
    limit: int
    offset: int
