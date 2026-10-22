"""Pydantic schemas for project roles (builder API layer)."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Role names follow the same snake_case identifier rules as field names but are
# forced to lowercase. Reserved words are checked in the validation module.
_ROLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_role_name(value: str) -> str:
    if not _ROLE_NAME_RE.match(value):
        raise ValueError(
            "role name must start with a lowercase letter and contain only "
            "lowercase letters, digits, and underscores"
        )
    return value


class ProjectRoleCreate(BaseModel):
    """Request body for POST /projects/{id}/roles."""

    name: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=100)
    is_default: bool = False
    self_assignable: bool = False
    invite_only: bool = False
    inherits_from: str | None = Field(default=None, max_length=60)
    position: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_role_name(v)

    @field_validator("inherits_from")
    @classmethod
    def validate_inherits_from(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_role_name(v)
        return v


class ProjectRoleUpdate(BaseModel):
    """Request body for PATCH /projects/{id}/roles/{name}."""

    label: str | None = Field(default=None, min_length=1, max_length=100)
    is_default: bool | None = None
    self_assignable: bool | None = None
    invite_only: bool | None = None
    inherits_from: str | None = Field(default=None, max_length=60)
    position: int | None = Field(default=None, ge=0)


class ProjectRoleRead(BaseModel):
    """Response body for role endpoints."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    label: str
    is_default: bool
    self_assignable: bool
    invite_only: bool
    inherits_from: str | None
    position: int
    created_at: datetime
    updated_at: datetime
