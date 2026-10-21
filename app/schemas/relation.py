import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import OnDelete, RelationKind

_NAME_RE = r"^[a-z][a-z0-9_]*$"


class RelationCreate(BaseModel):
    kind: RelationKind
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    from_name: str = Field(min_length=1, max_length=100, pattern=_NAME_RE)
    to_name: str = Field(min_length=1, max_length=100, pattern=_NAME_RE)
    on_delete: OnDelete = OnDelete.restrict
    required: bool = False


class RelationUpdate(BaseModel):
    from_name: str | None = Field(default=None, min_length=1, max_length=100, pattern=_NAME_RE)
    to_name: str | None = Field(default=None, min_length=1, max_length=100, pattern=_NAME_RE)
    on_delete: OnDelete | None = None
    required: bool | None = None


class RelationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    kind: RelationKind
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    from_name: str
    to_name: str
    on_delete: OnDelete
    required: bool
    created_at: datetime
    updated_at: datetime
