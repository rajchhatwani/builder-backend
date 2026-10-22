"""The SPEC: the contract between the builder API and the generator (PLAN.md section 3).

Deliberately lenient about *values* (plain `str` for names and enum-like fields, no
patterns or length limits). Rejecting bad values is `validation.validate`'s job, so one
call can report every issue instead of stopping at the first Pydantic error. Structure
is strict (`extra="forbid"`, correct JSON types) so nothing is silently dropped on import.

Relations reference entities by *name*, not id, so a spec is portable between projects.
Field order is the list order (no `position`); entities and relations are emitted sorted
so the same model always serializes to the same spec.
"""

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SPEC_VERSION = 1
ALLOWED_OPERATIONS = frozenset({"list", "get", "create", "replace", "update", "delete", "head"})


class _SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpecProject(_SpecModel):
    name: str
    slug: str
    description: str | None = None
    db_engine: str = "postgres"


class SpecEntityOptions(_SpecModel):
    operations: list[str] = Field(default_factory=lambda: sorted(ALLOWED_OPERATIONS))
    filterable: list[str] = Field(default_factory=list)
    sortable: list[str] = Field(default_factory=list)
    searchable: list[str] = Field(default_factory=list)
    default_page_size: int = 20
    max_page_size: int = 100
    soft_delete: bool = False


class SpecField(_SpecModel):
    name: str
    type: str
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: Any | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None


class SpecEntity(_SpecModel):
    name: str
    table_name: str
    plural_path: str
    options: SpecEntityOptions = Field(default_factory=SpecEntityOptions)
    fields: list[SpecField] = Field(default_factory=list)


class SpecRelation(_SpecModel):
    kind: str
    from_entity: str
    to_entity: str
    from_name: str
    to_name: str
    on_delete: str = "restrict"
    required: bool = False


class Spec(_SpecModel):
    spec_version: int = SPEC_VERSION
    project: SpecProject
    entities: list[SpecEntity] = Field(default_factory=list)
    relations: list[SpecRelation] = Field(default_factory=list)
    # Phase 2 hooks (PLAN.md section 13): accepted by the schema, rejected by validation
    # while non-empty, because nothing stores or generates them yet.
    features: list[str] = Field(default_factory=list)
    auth: dict[str, Any] | None = None


def spec_hash(spec: Spec) -> str:
    """Stable SHA-256 of the spec's canonical JSON; identical specs hash identically."""
    canonical = json.dumps(
        spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
