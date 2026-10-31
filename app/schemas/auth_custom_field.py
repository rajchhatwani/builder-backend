"""Pydantic schemas for auth custom registration fields (builder API layer)."""

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import AuthCustomFieldType

# Field names share the project's general snake_case identifier rules.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Types that accept string-length constraints
_STRING_LIKE = frozenset(
    {
        AuthCustomFieldType.string,
        AuthCustomFieldType.text,
        AuthCustomFieldType.email,
        AuthCustomFieldType.phone,
        AuthCustomFieldType.url,
    }
)

# Types that accept numeric range constraints
_NUMERIC = frozenset(
    {
        AuthCustomFieldType.integer,
        AuthCustomFieldType.float,
    }
)


class AuthCustomFieldCreate(BaseModel):
    """Request body for POST /projects/{id}/auth/custom-fields."""

    name: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    type: AuthCustomFieldType
    required: bool = False
    unique: bool = False
    indexed: bool = False

    # String constraints (only for string-like types)
    min_length: int | None = Field(default=None, ge=0, le=10_000)
    max_length: int | None = Field(default=None, ge=1, le=10_000)

    # Numeric constraints (only for integer / float)
    min_value: float | None = None
    max_value: float | None = None

    # Default value stored as string; generator casts to Python type
    default_value: str | None = Field(default=None, max_length=500)

    # Required for type='enum'
    enum_values: list[str] | None = Field(default=None, max_length=100)

    # Extra metadata reserved for future use (e.g. regex, UI hint)
    extra: dict[str, Any] | None = None

    position: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                "name must start with a lowercase letter and contain only "
                "lowercase letters, digits, and underscores"
            )
        return v

    @field_validator("enum_values")
    @classmethod
    def validate_enum_values_not_empty(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) == 0:
            raise ValueError("enum_values must contain at least one value")
        return v

    @model_validator(mode="after")
    def check_type_constraints(self) -> "AuthCustomFieldCreate":
        t = self.type

        # enum must have values
        if t == AuthCustomFieldType.enum and not self.enum_values:
            raise ValueError("enum_values is required for type 'enum'")
        if t != AuthCustomFieldType.enum and self.enum_values is not None:
            raise ValueError("enum_values is only valid for type 'enum'")

        # string constraints only on string-like
        if t not in _STRING_LIKE and (self.min_length is not None or self.max_length is not None):
            raise ValueError(f"min_length / max_length are not applicable for type '{t}'")

        # numeric constraints only on numeric
        if t not in _NUMERIC and (self.min_value is not None or self.max_value is not None):
            raise ValueError(f"min_value / max_value are not applicable for type '{t}'")

        # min ≤ max for strings
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("min_length must be ≤ max_length")

        # min ≤ max for numerics
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("min_value must be ≤ max_value")

        return self


class AuthCustomFieldUpdate(BaseModel):
    """Request body for PATCH /projects/{id}/auth/custom-fields/{id}."""

    label: str | None = Field(default=None, min_length=1, max_length=100)
    required: bool | None = None
    unique: bool | None = None
    indexed: bool | None = None
    min_length: int | None = Field(default=None, ge=0, le=10_000)
    max_length: int | None = Field(default=None, ge=1, le=10_000)
    min_value: float | None = None
    max_value: float | None = None
    default_value: str | None = Field(default=None, max_length=500)
    enum_values: list[str] | None = Field(default=None, max_length=100)
    extra: dict[str, Any] | None = None
    position: int | None = Field(default=None, ge=0)


class AuthCustomFieldRead(BaseModel):
    """Response body for auth custom field endpoints."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    label: str
    type: AuthCustomFieldType
    required: bool
    unique: bool
    indexed: bool
    min_length: int | None
    max_length: int | None
    min_value: float | None
    max_value: float | None
    default_value: str | None
    enum_values: list[str] | None
    extra: dict[str, Any] | None
    position: int
    created_at: datetime
    updated_at: datetime
