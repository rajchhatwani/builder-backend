import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_ALLOWED_OPERATIONS = {"list", "get", "create", "replace", "update", "delete", "head"}
_NAME_RE = r"^[A-Z][A-Za-z0-9]*$"


class EntityOptions(BaseModel):
    operations: list[str] = Field(default_factory=lambda: sorted(_ALLOWED_OPERATIONS))
    filterable: list[str] = Field(default_factory=list)
    sortable: list[str] = Field(default_factory=list)
    searchable: list[str] = Field(default_factory=list)
    default_page_size: int = Field(default=20, ge=1, le=500)
    max_page_size: int = Field(default=100, ge=1, le=1000)
    soft_delete: bool = False

    @field_validator("operations")
    @classmethod
    def validate_operations(cls, value: list[str]) -> list[str]:
        unknown = set(value) - _ALLOWED_OPERATIONS
        if unknown:
            raise ValueError(f"unknown operations: {sorted(unknown)}")
        return value


class EntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=_NAME_RE)
    table_name: str | None = Field(default=None, max_length=100)
    plural_path: str | None = Field(default=None, max_length=100)
    options: EntityOptions = Field(default_factory=EntityOptions)


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100, pattern=_NAME_RE)
    table_name: str | None = Field(default=None, max_length=100)
    plural_path: str | None = Field(default=None, max_length=100)
    options: EntityOptions | None = None


class EntityRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    table_name: str
    plural_path: str
    options: EntityOptions
    created_at: datetime
    updated_at: datetime
