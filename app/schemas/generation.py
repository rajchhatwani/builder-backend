import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.migration_plan import MigrationPlanResponse


class FileInfo(BaseModel):
    path: str
    size: int


class PreviewResponse(BaseModel):
    spec_hash: str
    total_files: int
    total_size: int
    files: list[FileInfo]
    migration: MigrationPlanResponse | None = None


class GenerationSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    spec_hash: str
    file_count: int
    total_size: int
    created_at: datetime


class GenerationDetail(GenerationSummary):
    spec_snapshot: dict[str, Any]
    file_manifest: list[dict[str, Any]]
