import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import FieldType

_NAME_RE = r"^[a-z][a-z0-9_]*$"


class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=_NAME_RE)
    type: FieldType
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: Any | None = None
    max_length: int | None = Field(default=None, ge=1)
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None
    position: int | None = Field(default=None, ge=0)


class FieldUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100, pattern=_NAME_RE)
    type: FieldType | None = None
    required: bool | None = None
    unique: bool | None = None
    indexed: bool | None = None
    default: Any | None = None
    max_length: int | None = Field(default=None, ge=1)
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None
    position: int | None = Field(default=None, ge=0)


class FieldRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    entity_id: uuid.UUID
    name: str
    type: FieldType
    required: bool
    unique: bool
    indexed: bool
    default: Any | None
    max_length: int | None
    min_value: float | None
    max_value: float | None
    enum_values: list[str] | None
    position: int
    created_at: datetime
    updated_at: datetime
