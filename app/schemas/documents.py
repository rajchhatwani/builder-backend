"""Pydantic schemas for the PDF document templates of a project.

Shapes and sizes are checked here; whether a template is legal (block types, placeholders, roles,
entities) is `validation.validate`'s job, so the dashboard can save a draft and read every problem.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocTemplateBody(BaseModel):
    id: str = Field(max_length=60)
    title: str = Field(default="", max_length=120)
    kind: str = Field(default="custom", max_length=40)
    entity: str | None = Field(default=None, max_length=100)
    compute: str | None = Field(default=None, max_length=60)
    roles: list[str] = Field(default_factory=list, max_length=50)
    template: dict[str, Any] = Field(default_factory=dict)


class DocumentsBody(BaseModel):
    enabled: bool = True
    rate_limit: str = Field(default="30/minute", max_length=20)
    templates: list[DocTemplateBody] = Field(default_factory=list, max_length=100)


class DocumentsWrite(DocumentsBody):
    """Body of PUT /projects/{id}/documents. `expected_version` guards against lost updates."""

    expected_version: int | None = Field(default=None, ge=0)


class DocumentsRead(DocumentsBody):
    project_id: uuid.UUID
    version: int  # 0 = never saved
    updated_at: datetime | None = None


class DocumentsIssues(BaseModel):
    issues: list[dict[str, str]]


class LibraryItem(BaseModel):
    id: str
    title: str
    industries: list[str]
    why: str
    compute: str | None
    template: dict[str, Any]
    sample: dict[str, Any]


class PreviewRequest(BaseModel):
    """Render a template with data and return the PDF, without saving anything."""

    template: dict[str, Any]
    data: dict[str, Any] = Field(default_factory=dict)
    compute: str | None = Field(default=None, max_length=60)
