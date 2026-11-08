# ruff: noqa: E501
"""Schema snapshot of a spec and the raw, unclassified differences between two snapshots."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.core.enums import FieldType
from app.core.spec_models import Spec

from .model import MigrationPlanError
from .rename import Rename

_VALID_TYPES = {t.value for t in FieldType}


@dataclass(frozen=True)
class Col:
    name: str
    type: str
    required: bool
    unique: bool
    indexed: bool
    default: Any
    max_length: int | None
    enum_values: tuple[str, ...] | None


@dataclass
class Table:
    entity: str
    table: str
    cols: list[Col]
    soft_delete: bool = False


@dataclass(frozen=True)
class Rel:
    kind: str
    from_entity: str
    to_entity: str
    from_name: str
    to_name: str
    on_delete: str
    required: bool

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.from_entity, self.from_name, self.to_entity, self.to_name)

    @property
    def is_join(self) -> bool:
        return self.kind == "many_to_many"

    @property
    def fk_column(self) -> str:
        return f"{self.to_name}_id"

    @property
    def join_table(self) -> str:
        return f"{self.from_entity}_{self.from_name}".lower()


@dataclass
class Snapshot:
    tables: dict[str, Table] = field(default_factory=dict)
    rels: dict[tuple[str, str, str, str], Rel] = field(default_factory=dict)
    multi_tenant: bool = False


def coerce_spec(raw: Any, label: str) -> Spec:
    if isinstance(raw, Spec):
        spec = raw
    elif isinstance(raw, dict):
        try:
            spec = Spec.model_validate(raw)
        except ValidationError as exc:
            e = exc.errors()[0]
            raise MigrationPlanError(f"{label} spec is malformed at {list(e['loc'])}: {e['msg']}") from exc
    else:
        raise MigrationPlanError(f"{label} spec must be a Spec or a dict, got {type(raw).__name__}")
    return spec


def snapshot(spec: Spec, label: str) -> Snapshot:
    snap = Snapshot(multi_tenant=bool(spec.auth and spec.auth.enabled and spec.auth.multi_tenant))
    tables_seen: set[str] = set()
    for e in spec.entities:
        if not e.name or not e.table_name:
            raise MigrationPlanError(f"{label} spec: entity with empty name or table_name")
        if e.name in snap.tables:
            raise MigrationPlanError(f"{label} spec: duplicate entity {e.name!r}")
        if e.table_name in tables_seen:
            raise MigrationPlanError(f"{label} spec: duplicate table_name {e.table_name!r}")
        tables_seen.add(e.table_name)
        cols: list[Col] = []
        names: set[str] = set()
        for f in e.fields:
            if f.type not in _VALID_TYPES:
                raise MigrationPlanError(f"{label} spec: {e.name}.{f.name} has unknown type {f.type!r}")
            if not f.name or f.name in names:
                raise MigrationPlanError(f"{label} spec: {e.name} has an empty or duplicate field {f.name!r}")
            names.add(f.name)
            if f.type == "enum" and not f.enum_values:
                raise MigrationPlanError(f"{label} spec: enum field {e.name}.{f.name} has no values")
            cols.append(
                Col(
                    f.name,
                    f.type,
                    f.required,
                    f.unique,
                    f.indexed,
                    f.default,
                    f.max_length,
                    tuple(f.enum_values) if f.enum_values is not None else None,
                )
            )
        snap.tables[e.name] = Table(e.name, e.table_name, cols, e.options.soft_delete)
    for r in spec.relations:
        for end in (r.from_entity, r.to_entity):
            if end not in snap.tables:
                raise MigrationPlanError(f"{label} spec: relation refers to unknown entity {end!r}")
        rel = Rel(r.kind, r.from_entity, r.to_entity, r.from_name, r.to_name, r.on_delete, r.required)
        if rel.key in snap.rels:
            raise MigrationPlanError(f"{label} spec: duplicate relation {rel.key}")
        snap.rels[rel.key] = rel
    return snap


@dataclass
class Aligned:
    old: Snapshot
    renamed_entities: set[str]  # NEW entity names that were renamed by a declared hint
    renamed_columns: dict[tuple[str, str], str]  # (new entity, NEW column) -> old column name


def apply_renames(old: Snapshot, new: Snapshot, renames: list[Rename]) -> Aligned:
    """Rewrite the OLD snapshot so declared renames line up with NEW."""
    ent_map: dict[str, str] = {}  # old name -> new name
    for r in renames:
        if r.kind != "entity":
            continue
        if r.from_ not in old.tables:
            raise MigrationPlanError(f"rename: entity {r.from_!r} does not exist in the old spec")
        if r.to not in new.tables:
            raise MigrationPlanError(f"rename: entity {r.to!r} does not exist in the new spec")
        if r.to in old.tables:
            raise MigrationPlanError(f"rename: target entity {r.to!r} already exists in the old spec")
        ent_map[r.from_] = r.to
    inv = {v: k for k, v in ent_map.items()}
    if len(inv) != len(ent_map):
        raise MigrationPlanError("rename: two entities renamed to the same name")
    out = Snapshot(multi_tenant=old.multi_tenant)
    for name, t in old.tables.items():
        nn = ent_map.get(name, name)
        out.tables[nn] = Table(nn, t.table, list(t.cols), t.soft_delete)
    for rel in old.rels.values():
        fe, te = ent_map.get(rel.from_entity, rel.from_entity), ent_map.get(rel.to_entity, rel.to_entity)
        nr = Rel(rel.kind, fe, te, rel.from_name, rel.to_name, rel.on_delete, rel.required)
        out.rels[nr.key] = nr
    col_renames: dict[tuple[str, str], str] = {}
    for r in renames:
        if r.kind != "field":
            continue
        assert r.entity is not None
        ent = r.entity if r.entity in out.tables else ent_map.get(r.entity, r.entity)
        if ent not in out.tables or ent not in new.tables:
            raise MigrationPlanError(f"rename: entity {r.entity!r} not found for field rename {r.from_!r}")
        cols = out.tables[ent].cols
        idx = next((i for i, c in enumerate(cols) if c.name == r.from_), None)
        if idx is None:
            raise MigrationPlanError(f"rename: field {ent}.{r.from_} does not exist in the old spec")
        if any(c.name == r.to for c in cols):
            raise MigrationPlanError(f"rename: target field {ent}.{r.to} already exists in the old spec")
        if not any(c.name == r.to for c in new.tables[ent].cols):
            raise MigrationPlanError(f"rename: field {ent}.{r.to} does not exist in the new spec")
        c = cols[idx]
        cols[idx] = Col(r.to, c.type, c.required, c.unique, c.indexed, c.default, c.max_length, c.enum_values)
        col_renames[(ent, r.to)] = r.from_
    return Aligned(out, set(ent_map.values()), col_renames)
