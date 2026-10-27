import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DbEngine

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    db_engine: DbEngine = DbEngine.postgres
    # The org to create it in (must be a member). Omitted: the creator's default org.
    organization_id: uuid.UUID | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is not None and not _SLUG_RE.match(value):
            raise ValueError(
                "slug must be lowercase letters, digits and hyphens, starting with a letter"
            )
        return value


class ProjectUpdate(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is not None and not _SLUG_RE.match(value):
            raise ValueError(
                "slug must be lowercase letters, digits and hyphens, starting with a letter"
            )
        return value


class ProjectRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    db_engine: DbEngine
    version: int
    organization_id: uuid.UUID | None = None
    # Set by `GET /projects`: the project's org is waiting for deletion, so opening the
    # project answers 423 until an owner cancels the request.
    organization_locked: bool = False
    organization_deletion_scheduled_for: datetime | None = None
    created_at: datetime
    updated_at: datetime
