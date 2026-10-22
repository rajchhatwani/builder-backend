"""Pydantic schemas for project permissions (builder API layer).

Permissions are managed as a bulk-upsert matrix: the client sends the full set
of (entity, operation) → (roles, row_rule) mappings and the service reconciles
them.  Individual rows can also be fetched, updated, and deleted.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AuthOperation, RowRule


class PermissionEntry(BaseModel):
    """A single (entity × operation) permission slot in a bulk upsert."""

    entity_id: uuid.UUID
    operation: AuthOperation
    # Empty list = publicly accessible; non-empty = requires one of these roles.
    roles: list[str] = Field(default_factory=list, max_length=50)
    row_rule: RowRule | None = None
    # Required only when row_rule = 'custom_filter'
    custom_filter_field: str | None = Field(default=None, max_length=100)
    custom_filter_value: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_custom_filter_fields(self) -> "PermissionEntry":
        if self.row_rule == RowRule.custom_filter:
            if not self.custom_filter_field:
                raise ValueError(
                    "custom_filter_field is required when row_rule is 'custom_filter'"
                )
            if self.custom_filter_value is None:
                raise ValueError(
                    "custom_filter_value is required when row_rule is 'custom_filter'"
                )
        else:
            # Non-custom_filter row rules must not carry custom filter fields
            if self.custom_filter_field is not None or self.custom_filter_value is not None:
                raise ValueError(
                    "custom_filter_field / custom_filter_value are only valid "
                    "when row_rule is 'custom_filter'"
                )
        return self


class ProjectPermissionBulkUpsert(BaseModel):
    """Request body for POST /projects/{id}/permissions (full matrix replace).

    Entries with duplicate (entity_id, operation) pairs within the same request
    are rejected by the service before touching the DB.
    """

    permissions: list[PermissionEntry] = Field(min_length=1, max_length=500)


class ProjectPermissionUpdate(BaseModel):
    """Request body for PATCH /projects/{id}/permissions/{permission_id}."""

    roles: list[str] | None = Field(default=None, max_length=50)
    row_rule: RowRule | None = None
    custom_filter_field: str | None = Field(default=None, max_length=100)
    custom_filter_value: str | None = Field(default=None, max_length=500)


class ProjectPermissionRead(BaseModel):
    """Response body for permission endpoints."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    entity_id: uuid.UUID
    operation: AuthOperation
    roles: list[str]
    row_rule: RowRule | None
    custom_filter_field: str | None
    custom_filter_value: str | None
    created_at: datetime
    updated_at: datetime
