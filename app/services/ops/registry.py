"""The closed registry of typed spec operations (architecture section 3).

Pure logic, no database. Each operation has a Pydantic payload model, `to_spec` (the spec the
operation produces from a given spec; used to dry-run, to verify and to compute inverses) and
`inverse` (the operation that takes it back). An operation whose natural inverse cannot be
proven (`to_spec(after, inverse) == before`, for example a delete that cascaded) falls back to
`replace_spec` with a snapshot, so every recorded inverse is exact. An `op_type` outside this
registry is rejected with 422.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, field_validator

from app.core.naming import pluralize, to_snake_case
from app.core.spec_models import (
    Spec,
    SpecEntity,
    SpecEntityOptions,
    SpecField,
    SpecRelation,
)
from app.exceptions import AppError
from app.models.enums import OnDelete, RelationKind
from app.schemas.entity import EntityCreate, EntityUpdate
from app.schemas.field import FieldCreate, FieldUpdate
from app.schemas.relation import RelationUpdate
from app.services.ops.canon import canonical_bytes, normalize

SECTIONS = ("state_machines", "settings", "sequences", "lists", "history", "hooks", "seed")


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _bad(message: str) -> AppError:
    return AppError(code="invalid_op", message=message, status_code=422)


def _not_found(what: str) -> AppError:
    return AppError(code="not_found", message=f"{what} not found", status_code=404)


def _conflict(message: str) -> AppError:
    return AppError(code="conflict", message=message, status_code=409)


def _changes(value: dict[str, Any], schema: type[BaseModel]) -> dict[str, Any]:
    if not value:
        raise ValueError("changes must name at least one attribute")
    unknown = sorted(set(value) - set(schema.model_fields))
    if unknown:
        raise ValueError(f"unknown attribute(s): {unknown}")
    checked = schema.model_validate(value)
    return checked.model_dump(mode="json", exclude_unset=True)


# -- payloads ----------------------------------------------------------------------------


class EntityDraft(_P):
    name: str
    table_name: str | None = None
    plural_path: str | None = None
    options: SpecEntityOptions | None = None
    fields: list[SpecField] = []

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        EntityCreate(name=v)
        return v

    def resolved(self) -> SpecEntity:
        plural = pluralize(to_snake_case(self.name))
        return SpecEntity(
            name=self.name,
            table_name=self.table_name or plural,
            plural_path=self.plural_path or plural,
            options=self.options or SpecEntityOptions(),
            fields=list(self.fields),
        )


class AddEntity(_P):
    entity: EntityDraft


class UpdateEntity(_P):
    name: str
    changes: dict[str, Any]

    @field_validator("changes")
    @classmethod
    def _c(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _changes(v, EntityUpdate)


class RemoveEntity(_P):
    name: str


class AddField(_P):
    entity: str
    field: SpecField
    index: int | None = None

    @field_validator("field")
    @classmethod
    def _f(cls, v: SpecField) -> SpecField:
        FieldCreate.model_validate(v.model_dump())
        return v

    @field_validator("index")
    @classmethod
    def _i(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("index must be >= 0")
        return v


class UpdateField(_P):
    entity: str
    name: str
    changes: dict[str, Any]

    @field_validator("changes")
    @classmethod
    def _c(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "position" in v:
            raise ValueError("field order is changed with add_field/remove_field, not position")
        return _changes(v, FieldUpdate)


class RemoveField(_P):
    entity: str
    name: str


class AddRelation(_P):
    relation: SpecRelation

    @field_validator("relation")
    @classmethod
    def _r(cls, v: SpecRelation) -> SpecRelation:
        RelationKind(v.kind)
        OnDelete(v.on_delete)
        return v


class UpdateRelation(_P):
    from_entity: str
    from_name: str
    to_entity: str
    changes: dict[str, Any]

    @field_validator("changes")
    @classmethod
    def _c(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _changes(v, RelationUpdate)


class RemoveRelation(_P):
    from_entity: str
    from_name: str
    to_entity: str


class SetSection(_P):
    """Whole-section replace of one behaviour section (state machines, settings, ...)."""

    section: Literal["state_machines", "settings", "sequences", "lists", "history", "hooks", "seed"]
    items: list[dict[str, Any]]

    @field_validator("items")
    @classmethod
    def _items(cls, v: list[dict[str, Any]], info: Any) -> list[dict[str, Any]]:
        section = info.data.get("section")
        if section is None:
            return v
        adapter = section_adapter(section)
        return [m.model_dump(mode="json") for m in adapter.validate_python(v)]


class ReplaceSpec(_P):
    spec: Spec


_ADAPTERS: dict[str, TypeAdapter[Any]] = {}


def section_adapter(section: str) -> TypeAdapter[Any]:
    if section not in _ADAPTERS:
        _ADAPTERS[section] = TypeAdapter(cast(Any, Spec.model_fields[section].annotation))
    return _ADAPTERS[section]


# -- lookups on a spec -------------------------------------------------------------------


def _find_entity(spec: Spec, name: str) -> SpecEntity:
    for e in spec.entities:
        if e.name == name:
            return e
    raise _not_found(f"entity '{name}'")


def _find_field(entity: SpecEntity, name: str) -> int:
    for i, f in enumerate(entity.fields):
        if f.name == name:
            return i
    raise _not_found(f"field '{name}' on '{entity.name}'")


def _find_relation(spec: Spec, key: tuple[str, str, str]) -> int:
    for i, r in enumerate(spec.relations):
        if (r.from_entity, r.from_name, r.to_entity) == key:
            return i
    raise _not_found("relation")


def _rel_key(r: SpecRelation) -> tuple[str, str, str]:
    return (r.from_entity, r.from_name, r.to_entity)


def _entity_clash(spec: Spec, e: SpecEntity) -> None:
    for o in spec.entities:
        if o is e:
            continue
        if o.name == e.name or o.table_name == e.table_name or o.plural_path == e.plural_path:
            raise _conflict("an entity with this name, table name or plural path already exists")


# -- to_spec -----------------------------------------------------------------------------


def _add_entity(spec: Spec, p: AddEntity) -> Spec:
    out = spec.model_copy(deep=True)
    entity = p.entity.resolved()
    _entity_clash(out, entity)
    seen: set[str] = set()
    for f in entity.fields:
        if f.name in seen:
            raise _conflict("a field with this name already exists on this entity")
        seen.add(f.name)
    out.entities.append(entity)
    return normalize(out)


def _update_entity(spec: Spec, p: UpdateEntity) -> Spec:
    out = spec.model_copy(deep=True)
    entity = _find_entity(out, p.name)
    old = entity.name
    for key, value in p.changes.items():
        if key == "options":
            entity.options = SpecEntityOptions.model_validate(value)
        else:
            setattr(entity, key, value)
    _entity_clash(out, entity)
    if entity.name != old:
        for r in out.relations:
            if r.from_entity == old:
                r.from_entity = entity.name
            if r.to_entity == old:
                r.to_entity = entity.name
        if out.auth is not None:
            for perm in out.auth.permissions:
                if perm.entity == old:
                    perm.entity = entity.name
    return normalize(out)


def _remove_entity(spec: Spec, p: RemoveEntity) -> Spec:
    out = spec.model_copy(deep=True)
    _find_entity(out, p.name)
    out.entities = [e for e in out.entities if e.name != p.name]
    # The database cascades to relations and permissions of the entity; so does this.
    out.relations = [r for r in out.relations if p.name not in (r.from_entity, r.to_entity)]
    if out.auth is not None:
        out.auth.permissions = [x for x in out.auth.permissions if x.entity != p.name]
    return normalize(out)


def _add_field(spec: Spec, p: AddField) -> Spec:
    out = spec.model_copy(deep=True)
    entity = _find_entity(out, p.entity)
    if any(f.name == p.field.name for f in entity.fields):
        raise _conflict("a field with this name already exists on this entity")
    index = len(entity.fields) if p.index is None else min(p.index, len(entity.fields))
    entity.fields.insert(index, p.field.model_copy(deep=True))
    return normalize(out)


def _update_field(spec: Spec, p: UpdateField) -> Spec:
    out = spec.model_copy(deep=True)
    entity = _find_entity(out, p.entity)
    field = entity.fields[_find_field(entity, p.name)]
    for key, value in p.changes.items():
        setattr(field, key, value)
    if sum(1 for f in entity.fields if f.name == field.name) > 1:
        raise _conflict("a field with this name already exists on this entity")
    return normalize(out)


def _remove_field(spec: Spec, p: RemoveField) -> Spec:
    out = spec.model_copy(deep=True)
    entity = _find_entity(out, p.entity)
    del entity.fields[_find_field(entity, p.name)]
    return normalize(out)


def _add_relation(spec: Spec, p: AddRelation) -> Spec:
    out = spec.model_copy(deep=True)
    _find_entity(out, p.relation.from_entity)
    _find_entity(out, p.relation.to_entity)
    if any(_rel_key(r) == _rel_key(p.relation) for r in out.relations):
        raise _conflict("a relation with this from_entity/to_entity/from_name already exists")
    out.relations.append(p.relation.model_copy(deep=True))
    return normalize(out)


def _update_relation(spec: Spec, p: UpdateRelation) -> Spec:
    out = spec.model_copy(deep=True)
    rel = out.relations[_find_relation(out, (p.from_entity, p.from_name, p.to_entity))]
    for key, value in p.changes.items():
        setattr(rel, key, value.value if hasattr(value, "value") else value)
    keys = [_rel_key(r) for r in out.relations]
    if len(keys) != len(set(keys)):
        raise _conflict("a relation with this from_entity/to_entity/from_name already exists")
    return normalize(out)


def _remove_relation(spec: Spec, p: RemoveRelation) -> Spec:
    out = spec.model_copy(deep=True)
    del out.relations[_find_relation(out, (p.from_entity, p.from_name, p.to_entity))]
    return normalize(out)


def _set_section(spec: Spec, p: SetSection) -> Spec:
    out = spec.model_copy(deep=True)
    setattr(out, p.section, section_adapter(p.section).validate_python(p.items))
    return normalize(out)


def _replace_spec(spec: Spec, p: ReplaceSpec) -> Spec:
    out = p.spec.model_copy(deep=True)
    # Like SpecService.replace: the project's own identity is kept, the engine is taken.
    out.project = spec.project.model_copy(update={"db_engine": p.spec.project.db_engine})
    return normalize(out)


# -- inverses ----------------------------------------------------------------------------

Call = tuple[str, dict[str, Any]]


def dump(p: BaseModel) -> dict[str, Any]:
    return p.model_dump(mode="json")


def _old_values(obj: BaseModel, keys: Any) -> dict[str, Any]:
    full = obj.model_dump(mode="json")
    return {k: full[k] for k in keys}


def _inv_add_entity(before: Spec, p: AddEntity) -> Call:
    return "remove_entity", {"name": p.entity.name}


def _inv_update_entity(before: Spec, p: UpdateEntity) -> Call:
    entity = _find_entity(before, p.name)
    return "update_entity", {
        "name": p.changes.get("name", p.name),
        "changes": _old_values(entity, p.changes),
    }


def _inv_remove_entity(before: Spec, p: RemoveEntity) -> Call:
    entity = _find_entity(before, p.name)
    return "add_entity", {"entity": dump(entity)}


def _inv_add_field(before: Spec, p: AddField) -> Call:
    return "remove_field", {"entity": p.entity, "name": p.field.name}


def _inv_update_field(before: Spec, p: UpdateField) -> Call:
    entity = _find_entity(before, p.entity)
    field = entity.fields[_find_field(entity, p.name)]
    return "update_field", {
        "entity": p.entity,
        "name": p.changes.get("name", p.name),
        "changes": _old_values(field, p.changes),
    }


def _inv_remove_field(before: Spec, p: RemoveField) -> Call:
    entity = _find_entity(before, p.entity)
    i = _find_field(entity, p.name)
    return "add_field", {"entity": p.entity, "field": dump(entity.fields[i]), "index": i}


def _inv_add_relation(before: Spec, p: AddRelation) -> Call:
    r = p.relation
    return "remove_relation", {
        "from_entity": r.from_entity,
        "from_name": r.from_name,
        "to_entity": r.to_entity,
    }


def _inv_update_relation(before: Spec, p: UpdateRelation) -> Call:
    rel = before.relations[_find_relation(before, (p.from_entity, p.from_name, p.to_entity))]
    return "update_relation", {
        "from_entity": p.from_entity,
        "from_name": p.changes.get("from_name", p.from_name),
        "to_entity": p.to_entity,
        "changes": _old_values(rel, p.changes),
    }


def _inv_remove_relation(before: Spec, p: RemoveRelation) -> Call:
    rel = before.relations[_find_relation(before, (p.from_entity, p.from_name, p.to_entity))]
    return "add_relation", {"relation": dump(rel)}


def _inv_set_section(before: Spec, p: SetSection) -> Call:
    old = [m.model_dump(mode="json") for m in getattr(before, p.section)]
    return "set_section", {"section": p.section, "items": old}


def _inv_replace_spec(before: Spec, p: ReplaceSpec) -> Call:
    return "replace_spec", {"spec": dump(before)}


@dataclass(frozen=True)
class OpDef:
    model: type[BaseModel]
    to_spec: Callable[[Spec, Any], Spec]
    inverse: Callable[[Spec, Any], Call]


REGISTRY: dict[str, OpDef] = {
    "add_entity": OpDef(AddEntity, _add_entity, _inv_add_entity),
    "update_entity": OpDef(UpdateEntity, _update_entity, _inv_update_entity),
    "remove_entity": OpDef(RemoveEntity, _remove_entity, _inv_remove_entity),
    "add_field": OpDef(AddField, _add_field, _inv_add_field),
    "update_field": OpDef(UpdateField, _update_field, _inv_update_field),
    "remove_field": OpDef(RemoveField, _remove_field, _inv_remove_field),
    "add_relation": OpDef(AddRelation, _add_relation, _inv_add_relation),
    "update_relation": OpDef(UpdateRelation, _update_relation, _inv_update_relation),
    "remove_relation": OpDef(RemoveRelation, _remove_relation, _inv_remove_relation),
    "set_section": OpDef(SetSection, _set_section, _inv_set_section),
    "replace_spec": OpDef(ReplaceSpec, _replace_spec, _inv_replace_spec),
}


def parse(op_type: str, payload: dict[str, Any]) -> BaseModel:
    """The payload as its model. Unknown op_type or a bad payload is a 422, never a 500; the
    error details name the paths, never the submitted values."""
    definition = REGISTRY.get(op_type)
    if definition is None:
        raise AppError(
            code="unknown_op_type",
            message=f"unknown op_type '{op_type[:60]}'",
            status_code=422,
            details=[{"allowed": sorted(REGISTRY)}],
        )
    try:
        return definition.model.model_validate(payload)
    except ValidationError as exc:
        raise AppError(
            code="invalid_op_payload",
            message="the operation payload is invalid",
            status_code=422,
            details=[
                {"path": ".".join(str(x) for x in e["loc"]), "message": e["msg"]}
                for e in exc.errors(include_input=False, include_url=False, include_context=False)
            ],
        ) from exc


@dataclass(frozen=True)
class Planned:
    op_type: str
    payload: BaseModel
    after: Spec  # the spec this operation must produce
    inverse_type: str
    inverse_payload: dict[str, Any]


def plan(before: Spec, op_type: str, payload: dict[str, Any]) -> Planned:
    """Dry run: the resulting spec and a proven inverse, without touching anything."""
    model = parse(op_type, payload)
    definition = REGISTRY[op_type]
    after = definition.to_spec(before, model)
    inv_type, inv_payload = definition.inverse(before, model)
    try:
        proven = canonical_bytes(
            REGISTRY[inv_type].to_spec(after, parse(inv_type, inv_payload))
        ) == canonical_bytes(before)
    except AppError:
        proven = False
    if not proven:
        inv_type, inv_payload = "replace_spec", dump(ReplaceSpec(spec=before))
    return Planned(op_type, model, after, inv_type, inv_payload)


# -- recognising a typed op in a before/after pair (for the legacy endpoints) -------------


def _changed(old: BaseModel, new: BaseModel, keys: tuple[str, ...]) -> dict[str, Any]:
    o, n = old.model_dump(mode="json"), new.model_dump(mode="json")
    return {k: n[k] for k in keys if o[k] != n[k]}


def _propose(b: Spec, a: Spec) -> Call | None:
    eb = {e.name: e for e in b.entities}
    ea = {e.name: e for e in a.entities}
    added, removed = sorted(set(ea) - set(eb)), sorted(set(eb) - set(ea))
    if len(added) == 1 and not removed:
        return "add_entity", {"entity": dump(ea[added[0]])}
    if len(removed) == 1 and not added:
        return "remove_entity", {"name": removed[0]}
    if added or removed:
        return None
    differing = [n for n in eb if eb[n].model_dump() != ea[n].model_dump()]
    if len(differing) > 1:
        return None
    if differing:
        name = differing[0]
        x, y = eb[name], ea[name]
        if x.fields != y.fields:
            fx, fy = [f.name for f in x.fields], [f.name for f in y.fields]
            if len(fy) == len(fx) + 1 and [n for n in fy if n in fx] == fx:
                i = next(i for i, n in enumerate(fy) if n not in fx)
                return "add_field", {"entity": name, "field": dump(y.fields[i]), "index": i}
            if len(fx) == len(fy) + 1 and [n for n in fx if n in fy] == fy:
                gone = next(n for n in fx if n not in fy)
                return "remove_field", {"entity": name, "name": gone}
            if fx == fy:
                diff = [i for i in range(len(fx)) if x.fields[i] != y.fields[i]]
                if len(diff) == 1:
                    keys = tuple(SpecField.model_fields)
                    ch = _changed(x.fields[diff[0]], y.fields[diff[0]], keys)
                    return "update_field", {"entity": name, "name": fx[diff[0]], "changes": ch}
            return None
        ch = _changed(x, y, ("table_name", "plural_path", "options"))
        return "update_entity", {"name": name, "changes": ch}
    rb = {_rel_key(r): r for r in b.relations}
    ra = {_rel_key(r): r for r in a.relations}
    add_r, rem_r = sorted(set(ra) - set(rb)), sorted(set(rb) - set(ra))
    if len(add_r) == 1 and not rem_r:
        return "add_relation", {"relation": dump(ra[add_r[0]])}
    if len(rem_r) == 1 and not add_r:
        k = rem_r[0]
        return "remove_relation", {"from_entity": k[0], "from_name": k[1], "to_entity": k[2]}
    if not add_r and not rem_r:
        diff_r = [k for k in rb if rb[k] != ra[k]]
        if len(diff_r) == 1:
            k = diff_r[0]
            ch = _changed(rb[k], ra[k], ("to_name", "on_delete", "required"))
            return "update_relation", {
                "from_entity": k[0],
                "from_name": k[1],
                "to_entity": k[2],
                "changes": ch,
            }
    return None


def recognise(before: Spec, after: Spec) -> Planned:
    """Describe the change `before -> after` as one typed op when it is exactly one (proved by
    re-applying it), else as `replace_spec` carrying the full new spec."""
    b, a = normalize(before), normalize(after)
    proposal = _propose(b, a)
    if proposal is not None:
        try:
            planned = plan(b, proposal[0], proposal[1])
            if canonical_bytes(planned.after) == canonical_bytes(a):
                return planned
        except AppError:
            pass
    return plan(b, "replace_spec", {"spec": dump(a)})
