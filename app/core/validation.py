"""validate(spec) -> list[ValidationIssue] (PLAN.md section 8).

Returns *every* issue, each with a `path` into the spec, a stable `code` and a message.
Nothing here touches the DB or FastAPI. The generator may assume a spec with no issues:
identifiers are safe to embed in code, SQL and file paths, names never collide, and
defaults match their field types.
"""

import json
import math
import re
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.core import naming
from app.core.enums import DbEngine, FieldType, OnDelete, RelationKind
from app.core.spec_models import (
    ALLOWED_OPERATIONS,
    SPEC_VERSION,
    Spec,
    SpecEntity,
    SpecEntityOptions,
    SpecField,
    SpecProject,
    SpecRelation,
)

MAX_ENTITIES = 100
MAX_FIELDS_PER_ENTITY = 100
MAX_RELATIONS = 300
MAX_ENUM_VALUES = 100
MAX_STRING_LENGTH = 10_000
MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 2000
MAX_PAGE_SIZE = 1000

_ENUM_VALUE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

_NUMERIC_TYPES = {FieldType.integer, FieldType.bigint, FieldType.float, FieldType.decimal}
_INT_RANGES = {
    FieldType.integer: (-(2**31), 2**31 - 1),
    FieldType.bigint: (-(2**63), 2**63 - 1),
}
_STRING_TYPES = {FieldType.string, FieldType.text}


class ValidationIssue(BaseModel):
    path: str
    code: str
    message: str


class _Ctx:
    """Collects issues plus the cross-entity state that name-collision checks need."""

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []
        # table name -> path that first defined it (entity tables and join tables)
        self.tables: dict[str, str] = {}
        # entity name -> {attribute/column name -> path that defined it, or "auto"}
        self.namespaces: dict[str, dict[str, str]] = {}
        # entity name -> table name
        self.entity_tables: dict[str, str] = {}

    def add(self, path: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(path=path, code=code, message=message))


def validate(spec: Spec) -> list[ValidationIssue]:
    ctx = _Ctx()
    if spec.spec_version != SPEC_VERSION:
        ctx.add(
            "spec_version",
            "unsupported_spec_version",
            f"spec_version must be {SPEC_VERSION}, got {spec.spec_version}",
        )
    if spec.features:
        ctx.add(
            "features",
            "unsupported_feature",
            "features is reserved for a later phase and must be empty",
        )
    if spec.auth is not None:
        # Auth block is accepted; deep validation added in M7 (auth generator module).
        pass


    _check_project(spec.project, ctx)
    _check_sizes(spec, ctx)
    entities_by_name = _check_entities(spec, ctx)
    _check_relations(spec, entities_by_name, ctx)
    return ctx.issues


# --- shared helpers ---------------------------------------------------------------------


def _identifier(
    ctx: _Ctx,
    path: str,
    value: str,
    pattern: re.Pattern[str],
    *,
    sql: bool,
    python: bool = True,
    attribute: bool = False,
) -> bool:
    """Check shape, length and reserved words. Returns True if the shape is valid, so
    callers can still run uniqueness checks on a name that is merely a reserved word."""
    if len(value) > naming.MAX_IDENTIFIER_LENGTH:
        ctx.add(
            path,
            "identifier_too_long",
            f"must be at most {naming.MAX_IDENTIFIER_LENGTH} characters",
        )
        return False
    if not pattern.fullmatch(value):
        ctx.add(
            path,
            "invalid_identifier",
            f"{value[:40]!r} does not match the required pattern {pattern.pattern}",
        )
        return False
    if python and naming.is_python_reserved(value):
        ctx.add(path, "reserved_word", f"{value!r} is a Python keyword or builtin")
    elif sql and naming.is_sql_reserved(value):
        ctx.add(path, "reserved_word", f"{value!r} is a reserved SQL word")
    elif attribute and naming.is_reserved_attribute(value):
        ctx.add(
            path,
            "reserved_word",
            f"{value!r} clashes with an attribute of the generated models and schemas",
        )
    return True


# --- project and sizes ------------------------------------------------------------------


def _check_project(project: SpecProject, ctx: _Ctx) -> None:
    if not project.name.strip() or len(project.name) > MAX_NAME_LENGTH:
        ctx.add("project.name", "invalid_name", f"must be 1-{MAX_NAME_LENGTH} non-blank characters")
    elif _CONTROL_CHARS_RE.search(project.name):
        ctx.add("project.name", "invalid_name", "must be a single line without control characters")
    if len(project.slug) > naming.MAX_IDENTIFIER_LENGTH or not naming.SLUG_RE.fullmatch(
        project.slug
    ):
        ctx.add(
            "project.slug",
            "invalid_identifier",
            "must be lowercase letters, digits and hyphens, starting with a letter, "
            f"at most {naming.MAX_IDENTIFIER_LENGTH} characters",
        )
    if project.description is not None and len(project.description) > MAX_DESCRIPTION_LENGTH:
        ctx.add(
            "project.description",
            "too_long",
            f"must be at most {MAX_DESCRIPTION_LENGTH} characters",
        )
    if project.db_engine != DbEngine.postgres:
        ctx.add("project.db_engine", "unsupported_value", "only 'postgres' is supported")


def _check_sizes(spec: Spec, ctx: _Ctx) -> None:
    if len(spec.entities) > MAX_ENTITIES:
        ctx.add("entities", "too_many", f"at most {MAX_ENTITIES} entities are allowed")
    if len(spec.relations) > MAX_RELATIONS:
        ctx.add("relations", "too_many", f"at most {MAX_RELATIONS} relations are allowed")


# --- entities and fields ----------------------------------------------------------------


def _check_entities(spec: Spec, ctx: _Ctx) -> dict[str, SpecEntity]:
    first_by_name: dict[str, SpecEntity] = {}
    paths_seen: dict[str, str] = {}
    class_names: dict[str, str] = {}  # generated class name -> path

    for i, entity in enumerate(spec.entities):
        p = f"entities[{i}]"
        name_ok = _identifier(ctx, f"{p}.name", entity.name, naming.ENTITY_NAME_RE, sql=False)
        is_first = entity.name not in first_by_name
        if name_ok and not is_first:
            ctx.add(f"{p}.name", "duplicate_name", f"entity name {entity.name!r} is already used")
        if name_ok:
            # Generated as {Name}, {Name}Create/Update/Read and {Name}Repository.
            for suffix in ("", "Create", "Update", "Read", "Repository"):
                cls = entity.name + suffix
                if cls in class_names and class_names[cls] != p:
                    ctx.add(
                        f"{p}.name",
                        "duplicate_name",
                        f"generated class {cls!r} collides with {class_names[cls]}",
                    )
                class_names.setdefault(cls, p)

        table_ok = _identifier(
            ctx, f"{p}.table_name", entity.table_name, naming.SNAKE_NAME_RE, sql=True
        )
        if table_ok:
            _claim_table(ctx, f"{p}.table_name", entity.table_name)
        path_ok = _identifier(
            ctx, f"{p}.plural_path", entity.plural_path, naming.SNAKE_NAME_RE, sql=False
        )
        if path_ok:
            if entity.plural_path in naming.RESERVED_PATHS:
                ctx.add(
                    f"{p}.plural_path",
                    "reserved_word",
                    f"{entity.plural_path!r} is served by the generated app itself",
                )
            if entity.plural_path in paths_seen:
                ctx.add(
                    f"{p}.plural_path",
                    "duplicate_name",
                    f"plural_path {entity.plural_path!r} is already used by "
                    f"{paths_seen[entity.plural_path]}",
                )
            paths_seen.setdefault(entity.plural_path, p)

        if name_ok and is_first:
            first_by_name[entity.name] = entity
            namespace = {name: "auto" for name in naming.AUTO_FIELDS}
            types = dict(naming.AUTO_FIELDS)
            if entity.options.soft_delete:
                namespace[naming.SOFT_DELETE_FIELD[0]] = "auto"
                types[naming.SOFT_DELETE_FIELD[0]] = naming.SOFT_DELETE_FIELD[1]
            ctx.namespaces[entity.name] = namespace
            if table_ok:
                ctx.entity_tables[entity.name] = entity.table_name
        else:
            # Unusable or duplicate entity: still check its contents against a scratch namespace.
            namespace = {name: "auto" for name in naming.AUTO_FIELDS}
            types = dict(naming.AUTO_FIELDS)

        _check_fields(entity, p, namespace, types, ctx)
        _check_options(entity.options, f"{p}.options", types, ctx)
    return first_by_name


def _claim_table(ctx: _Ctx, path: str, table: str) -> None:
    if table in naming.RESERVED_TABLES:
        ctx.add(path, "reserved_word", f"{table!r} is used by the migration tooling")
    elif table in ctx.tables:
        ctx.add(
            path, "duplicate_name", f"table name {table!r} is already used by {ctx.tables[table]}"
        )
    else:
        ctx.tables[table] = path


def _check_fields(
    entity: SpecEntity,
    entity_path: str,
    namespace: dict[str, str],
    types: dict[str, str],
    ctx: _Ctx,
) -> None:
    if len(entity.fields) > MAX_FIELDS_PER_ENTITY:
        ctx.add(
            f"{entity_path}.fields",
            "too_many",
            f"at most {MAX_FIELDS_PER_ENTITY} fields per entity are allowed",
        )
    for j, field in enumerate(entity.fields):
        p = f"{entity_path}.fields[{j}]"
        name_ok = _identifier(
            ctx, f"{p}.name", field.name, naming.SNAKE_NAME_RE, sql=True, attribute=True
        )
        if name_ok:
            existing = namespace.get(field.name)
            if existing == "auto":
                ctx.add(
                    f"{p}.name",
                    "reserved_name",
                    f"{field.name!r} is added automatically and cannot be redefined",
                )
            elif existing is not None:
                ctx.add(
                    f"{p}.name",
                    "duplicate_name",
                    f"{field.name!r} is already defined at {existing}",
                )
            else:
                namespace[field.name] = p
                types[field.name] = field.type
        _check_field_definition(field, p, ctx)


def _check_field_definition(field: SpecField, p: str, ctx: _Ctx) -> None:
    try:
        ftype = FieldType(field.type)
    except ValueError:
        allowed = ", ".join(t.value for t in FieldType)
        ctx.add(f"{p}.type", "unknown_type", f"{field.type!r} is not one of: {allowed}")
        return

    if ftype is FieldType.json and (field.unique or field.indexed):
        ctx.add(p, "unsupported_option", "json fields cannot be unique or indexed")

    if field.max_length is not None:
        if ftype is not FieldType.string:
            ctx.add(f"{p}.max_length", "unsupported_option", "max_length applies to string only")
        elif not 1 <= field.max_length <= MAX_STRING_LENGTH:
            ctx.add(
                f"{p}.max_length",
                "out_of_range",
                f"must be between 1 and {MAX_STRING_LENGTH}",
            )

    if ftype is FieldType.enum:
        _check_enum_values(field, p, ctx)
    elif field.enum_values is not None:
        ctx.add(f"{p}.enum_values", "unsupported_option", "enum_values applies to enum only")

    bounds_ok = _check_bounds(field, ftype, p, ctx)
    if field.default is not None:
        problem = _default_problem(field, ftype, bounds_ok)
        if problem:
            ctx.add(f"{p}.default", "invalid_default", problem)


def _check_enum_values(field: SpecField, p: str, ctx: _Ctx) -> None:
    values = field.enum_values
    if not values:
        ctx.add(f"{p}.enum_values", "enum_empty", "an enum field needs at least one value")
        return
    if len(values) > MAX_ENUM_VALUES:
        ctx.add(f"{p}.enum_values", "too_many", f"at most {MAX_ENUM_VALUES} values are allowed")
    if len(set(values)) != len(values):
        ctx.add(f"{p}.enum_values", "duplicate_name", "enum values must be unique")
    for k, value in enumerate(values):
        if not _ENUM_VALUE_RE.fullmatch(value):
            ctx.add(
                f"{p}.enum_values[{k}]",
                "invalid_identifier",
                "must be 1-64 characters from letters, digits, '_', '.' and '-'",
            )


def _check_bounds(field: SpecField, ftype: FieldType, p: str, ctx: _Ctx) -> bool:
    """Returns False when min/max are unusable, so the default isn't compared against them."""
    if field.min_value is None and field.max_value is None:
        return True
    if ftype not in _NUMERIC_TYPES:
        ctx.add(p, "unsupported_option", "min_value/max_value apply to numeric types only")
        return False
    ok = True
    for name, value in (("min_value", field.min_value), ("max_value", field.max_value)):
        if value is not None and not math.isfinite(value):
            ctx.add(f"{p}.{name}", "out_of_range", "must be a finite number")
            ok = False
    if (
        ok
        and field.min_value is not None
        and field.max_value is not None
        and field.min_value > field.max_value
    ):
        ctx.add(p, "invalid_range", "min_value must not exceed max_value")
        ok = False
    return ok


def _default_problem(field: SpecField, ftype: FieldType, bounds_ok: bool) -> str | None:
    value = field.default
    if ftype in _STRING_TYPES:
        if not isinstance(value, str):
            return "must be a string"
        if ftype is FieldType.string and field.max_length and len(value) > field.max_length:
            return f"is longer than max_length ({field.max_length})"
        return None
    if ftype in (FieldType.integer, FieldType.bigint):
        if not isinstance(value, int) or isinstance(value, bool):
            return "must be an integer"
        low, high = _INT_RANGES[ftype]
        if not low <= value <= high:
            return f"is outside the {ftype.value} range"
    elif ftype in (FieldType.float, FieldType.decimal):
        if not isinstance(value, int | float) or isinstance(value, bool):
            return "must be a finite number"
        if not math.isfinite(value):
            return "must be a finite number"
    elif ftype is FieldType.boolean:
        return None if isinstance(value, bool) else "must be true or false"
    elif ftype is FieldType.date:
        return None if _parses(value, date.fromisoformat) else "must be an ISO date (YYYY-MM-DD)"
    elif ftype is FieldType.datetime:
        return None if _parses(value, datetime.fromisoformat) else "must be an ISO 8601 datetime"
    elif ftype is FieldType.uuid:
        return None if _parses(value, uuid.UUID) else "must be a UUID string"
    elif ftype is FieldType.enum:
        if not isinstance(value, str) or value not in (field.enum_values or []):
            return "must be one of enum_values"
        return None
    else:  # json: any finite, serializable JSON value is acceptable
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            return "must be valid JSON without NaN or Infinity"
        return None

    if bounds_ok:
        number: float = value
        if field.min_value is not None and number < field.min_value:
            return "is below min_value"
        if field.max_value is not None and number > field.max_value:
            return "is above max_value"
    return None


def _parses(value: Any, parser: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parser(value)
    except ValueError:
        return False
    return True


def _check_options(options: SpecEntityOptions, p: str, types: dict[str, str], ctx: _Ctx) -> None:
    for k, op in enumerate(options.operations):
        if op not in ALLOWED_OPERATIONS:
            allowed = ", ".join(sorted(ALLOWED_OPERATIONS))
            ctx.add(f"{p}.operations[{k}]", "unknown_operation", f"{op!r} is not one of: {allowed}")
    if len(set(options.operations)) != len(options.operations):
        ctx.add(f"{p}.operations", "duplicate_name", "operations must be unique")

    _check_field_refs(options.filterable, f"{p}.filterable", types, ctx, excluded={"json"})
    for k, name in enumerate(options.filterable):
        if name in naming.RESERVED_QUERY_PARAMS:
            ctx.add(
                f"{p}.filterable[{k}]",
                "reserved_word",
                f"{name!r} is a query parameter of the list endpoint (limit, offset, sort, q)",
            )
    _check_field_refs(options.sortable, f"{p}.sortable", types, ctx, excluded={"json"})
    _check_field_refs(
        options.searchable,
        f"{p}.searchable",
        types,
        ctx,
        allowed={t.value for t in _STRING_TYPES},
    )

    if not 1 <= options.max_page_size <= MAX_PAGE_SIZE:
        ctx.add(f"{p}.max_page_size", "out_of_range", f"must be between 1 and {MAX_PAGE_SIZE}")
    if not 1 <= options.default_page_size <= options.max_page_size:
        ctx.add(
            f"{p}.default_page_size",
            "out_of_range",
            "must be between 1 and max_page_size",
        )


def _check_field_refs(
    names: list[str],
    p: str,
    types: dict[str, str],
    ctx: _Ctx,
    *,
    excluded: set[str] | None = None,
    allowed: set[str] | None = None,
) -> None:
    for k, name in enumerate(names):
        ftype = types.get(name)
        if ftype is None:
            ctx.add(f"{p}[{k}]", "unknown_field", f"{name!r} is not a field of this entity")
        elif excluded and ftype in excluded:
            ctx.add(f"{p}[{k}]", "incompatible_type", f"{ftype} fields cannot be used here")
        elif allowed is not None and ftype not in allowed:
            ctx.add(
                f"{p}[{k}]",
                "incompatible_type",
                f"only {', '.join(sorted(allowed))} fields can be used here, {name!r} is {ftype}",
            )


# --- relations --------------------------------------------------------------------------


def _check_relations(spec: Spec, entities: dict[str, SpecEntity], ctx: _Ctx) -> None:
    for i, rel in enumerate(spec.relations):
        p = f"relations[{i}]"
        kind = _check_relation_enums(rel, p, ctx)

        from_ok = _identifier(
            ctx, f"{p}.from_name", rel.from_name, naming.SNAKE_NAME_RE, sql=False, attribute=True
        )
        to_ok = _identifier(
            ctx, f"{p}.to_name", rel.to_name, naming.SNAKE_NAME_RE, sql=False, attribute=True
        )
        from_entity = _resolve(entities, rel.from_entity, f"{p}.from_entity", ctx)
        to_entity = _resolve(entities, rel.to_entity, f"{p}.to_entity", ctx)

        if from_entity is not None and from_ok:
            _claim_name(ctx, from_entity.name, rel.from_name, f"{p}.from_name")
        if to_entity is not None and to_ok:
            _claim_name(ctx, to_entity.name, rel.to_name, f"{p}.to_name")
            if kind in (RelationKind.one_to_many, RelationKind.one_to_one):
                column = naming.fk_column_name(rel.to_name)
                if len(column) > naming.MAX_IDENTIFIER_LENGTH:
                    ctx.add(f"{p}.to_name", "identifier_too_long", f"column {column!r} is too long")
                else:
                    _claim_name(ctx, to_entity.name, column, f"{p}.to_name")

        if (
            kind is RelationKind.many_to_many
            and from_entity is not None
            and from_ok
            and from_entity.name in ctx.entity_tables
        ):
            join = naming.join_table_name(ctx.entity_tables[from_entity.name], rel.from_name)
            if len(join) > naming.MAX_IDENTIFIER_LENGTH:
                ctx.add(p, "identifier_too_long", f"join table {join!r} is too long")
            else:
                _claim_table(ctx, p, join)

    _check_required_cycles(spec, entities, ctx)


def _check_required_cycles(spec: Spec, entities: dict[str, SpecEntity], ctx: _Ctx) -> None:
    """A required one_to_many/one_to_one puts a NOT NULL foreign key on the `to` entity, so
    `to` rows need a `from` row first. A cycle of those can never get its first row."""
    needs: dict[str, set[str]] = {}
    required: list[tuple[int, SpecRelation]] = []
    for i, rel in enumerate(spec.relations):
        if (
            rel.required
            and rel.kind in (RelationKind.one_to_many, RelationKind.one_to_one)
            and rel.from_entity in entities
            and rel.to_entity in entities
        ):
            needs.setdefault(rel.to_entity, set()).add(rel.from_entity)
            required.append((i, rel))
    for i, rel in required:
        seen: set[str] = set()
        stack = [rel.from_entity]
        while stack:
            current = stack.pop()
            if current == rel.to_entity:
                ctx.add(
                    f"relations[{i}]",
                    "required_cycle",
                    f"{rel.to_entity} and {rel.from_entity} require each other, so neither "
                    "could ever get a first row; make one relation optional",
                )
                break
            if current not in seen:
                seen.add(current)
                stack.extend(sorted(needs.get(current, ())))


def _check_relation_enums(rel: SpecRelation, p: str, ctx: _Ctx) -> RelationKind | None:
    kind: RelationKind | None = None
    try:
        kind = RelationKind(rel.kind)
    except ValueError:
        allowed = ", ".join(k.value for k in RelationKind)
        ctx.add(f"{p}.kind", "unknown_kind", f"{rel.kind!r} is not one of: {allowed}")
    on_delete: OnDelete | None = None
    try:
        on_delete = OnDelete(rel.on_delete)
    except ValueError:
        allowed = ", ".join(o.value for o in OnDelete)
        ctx.add(
            f"{p}.on_delete", "unknown_on_delete", f"{rel.on_delete!r} is not one of: {allowed}"
        )

    if on_delete is OnDelete.set_null:
        if rel.required:
            ctx.add(
                p, "incompatible_on_delete", "a required relation cannot use on_delete set_null"
            )
        if kind is RelationKind.many_to_many:
            ctx.add(p, "incompatible_on_delete", "many_to_many relations cannot use set_null")
    return kind


def _resolve(entities: dict[str, SpecEntity], name: str, path: str, ctx: _Ctx) -> SpecEntity | None:
    entity = entities.get(name)
    if entity is None:
        ctx.add(path, "unknown_entity", f"no entity named {name[:40]!r}")
    return entity


def _claim_name(ctx: _Ctx, entity_name: str, name: str, path: str) -> None:
    namespace = ctx.namespaces[entity_name]
    existing = namespace.get(name)
    if existing == "auto":
        ctx.add(path, "reserved_name", f"{name!r} is added automatically on {entity_name}")
    elif existing is not None:
        ctx.add(
            path, "duplicate_name", f"{name!r} on {entity_name} is already defined at {existing}"
        )
    else:
        namespace[name] = path
