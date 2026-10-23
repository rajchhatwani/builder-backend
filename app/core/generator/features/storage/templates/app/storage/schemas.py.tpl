"""Response shapes of the file API (generated). The storage key and the bucket never appear here."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    shared: bool
    # null once the file has been erased
    original_name: str | None
    content_type: str  # what the bytes are (detected), not what the uploader claimed
    size_bytes: int
    sha256: str
    created_by_id: uuid.UUID
    created_at: datetime
    scanned_at: datetime | None

    @classmethod
    def from_row(cls, row: Any) -> "FileRead":
        return cls(
            id=row.id,
            status=row.status,
            shared=row.shared,
            original_name=row.original_name,
            content_type=row.detected_type,
            size_bytes=row.size_bytes,
            sha256=row.sha256,
            created_by_id=row.created_by_id,
            created_at=row.created_at,
            scanned_at=row.scanned_at,
        )


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    at: datetime
    actor_id: uuid.UUID | None
    event: str
    outcome: str
    ip: str | None
    request_id: str | None
    data: dict[str, Any]
    hash: str


class AuditTrailRead(BaseModel):
    file_id: uuid.UUID
    chain_ok: bool
    first_bad_seq: int | None
    entries: list[AuditEntryRead]


class ScannerStatus(BaseModel):
    ok: bool
    engine: str | None


class BackendStatus(BaseModel):
    ok: bool


class StorageStatus(BaseModel):
    scanner: ScannerStatus
    bucket: BackendStatus
    max_file_bytes: int
    allowed_types: list[str]
    download_mode: str


class QuarantineRequest(BaseModel):
    reason: str = "manual"
