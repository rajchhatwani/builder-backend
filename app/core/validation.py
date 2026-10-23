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
from urllib.parse import urlsplit

from pydantic import BaseModel

from app.core import naming
from app.core.enums import (
    AuthCustomFieldType,
    AuthOperation,
    AuthProvider,
    DbEngine,
    FieldType,
    IdpType,
    JwtAlgorithm,
    KeycloakMode,
    MfaMode,
    OnDelete,
    RelationKind,
    RowRule,
    SmsProvider,
    TokenStore,
)
from app.core.spec_models import (
    ALLOWED_OPERATIONS,
    SPEC_VERSION,
    Spec,
    SpecAuth,
    SpecAuthCustomField,
    SpecEntity,
    SpecEntityOptions,
    SpecField,
    SpecKeycloak,
    SpecProject,
    SpecRelation,
)
from app.core.validation_payments import PAYMENTS_TABLES, check_payments, payments_active

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
    if spec.auth is not None and spec.auth.enabled:
        # Claim the auth tables first so an entity cannot silently shadow them.
        for table in auth_tables(spec.auth):
            ctx.tables[table] = "auth"
    if payments_active(spec):
        for table in PAYMENTS_TABLES:
            ctx.tables[table] = "payments"

    _check_project(spec.project, ctx)
    _check_sizes(spec, ctx)
    entities_by_name = _check_entities(spec, ctx)
    _check_relations(spec, entities_by_name, ctx)
    if spec.auth is not None:
        _check_auth(spec.auth, entities_by_name, ctx)
    check_payments(spec, entities_by_name, ctx.add, redirect_uri_problem)
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


# --- auth -------------------------------------------------------------------------------

# Tables the generated auth module creates; entities may not use these names.
AUTH_TABLES = (
    "auth_invitations",
    "auth_provider_lock",
    "auth_refresh_tokens",
    "auth_tenants",
    "auth_users",
    "auth_verification_codes",
)
# With Keycloak the identity provider owns passwords, tokens and invitations; the project keeps
# only a profile row per user (auth_users) and the provider lock.
KEYCLOAK_AUTH_TABLES = ("auth_provider_lock", "auth_tenants", "auth_users")


def auth_tables(auth: SpecAuth) -> tuple[str, ...]:
    """The tables the generated auth module creates for this spec."""
    return KEYCLOAK_AUTH_TABLES if auth.provider == AuthProvider.keycloak else AUTH_TABLES


def uses_keycloak(auth: SpecAuth | None) -> bool:
    return auth is not None and auth.enabled and auth.provider == AuthProvider.keycloak

# Columns of auth_users that custom registration fields may not reuse.
AUTH_USER_COLUMNS = frozenset(
    {
        "id",
        "email",
        "phone",
        "password",
        "password_hash",
        "roles",
        "is_active",
        "email_verified_at",
        "phone_verified_at",
        "last_login_at",
        "created_at",
        "updated_at",
        "deleted_at",
        "tenant_id",
        "tenant_name",
        "invite_token",
    }
)
_RATE_LIMIT_RE = re.compile(r"[0-9]{1,6}/[0-9]{0,4}(second|minute|hour|day)s?")
_EMAIL_RE = re.compile(r"[^@\s\"'<>]+@[^@\s\"'<>]+\.[^@\s\"'<>]+")
_HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_PHONE_E164_RE = re.compile(r"\+[1-9][0-9]{6,14}")
_SMS_SENDER_ID_RE = re.compile(r"[A-Za-z0-9]{1,11}")
_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")
_MAX_ROLES = 50
_MAX_CUSTOM_FIELDS = 30
_MAX_LABEL_LENGTH = 100
_MAX_AUTH_ENUM_VALUES = 50
_TEXT_LIKE = {"string", "text", "email", "phone", "url"}


def _single_line(value: str) -> bool:
    return (
        bool(value.strip())
        and len(value) <= _MAX_LABEL_LENGTH
        and not _CONTROL_CHARS_RE.search(value)
    )


def _check_auth(auth: SpecAuth, entities: dict[str, SpecEntity], ctx: _Ctx) -> None:
    # Structural checks run even when auth is switched off: the stored model must always
    # be importable, so enum values and permission references have to make sense.
    _check_auth_structure(auth, entities, ctx)
    if not auth.enabled:
        return
    if auth.provider == AuthProvider.keycloak:
        _check_auth_keycloak(auth, entities, ctx)
        return
    _check_auth_tokens(auth, ctx)
    _check_auth_tenancy(auth, ctx)
    _check_auth_email_sms(auth, ctx)
    _check_auth_branding(auth, ctx)
    _check_auth_roles(auth, ctx)
    _check_auth_custom_fields(auth, ctx)
    _check_auth_permission_rules(auth, entities, ctx)
    _check_auth_invitations(auth, ctx)


def _check_auth_tokens(auth: SpecAuth, ctx: _Ctx) -> None:
    bounds = (
        ("access_token_ttl_minutes", auth.access_token_ttl_minutes, 1, 1440),
        ("refresh_token_ttl_days", auth.refresh_token_ttl_days, 1, 365),
        ("password_reset.otp_ttl_minutes", auth.password_reset.otp_ttl_minutes, 1, 60),
    )
    for name, value, low, high in bounds:
        if not low <= value <= high:
            ctx.add(f"auth.{name}", "out_of_range", f"must be between {low} and {high}")
    for name in ("login_rate_limit", "register_rate_limit", "reset_rate_limit"):
        if not _RATE_LIMIT_RE.fullmatch(getattr(auth, name)):
            ctx.add(
                f"auth.{name}",
                "invalid_value",
                "must look like '5/minute', '10/hour' or '5/15minutes'",
            )


def _check_auth_structure(auth: SpecAuth, entities: dict[str, SpecEntity], ctx: _Ctx) -> None:
    for path, value, allowed in (
        ("auth.token_store", auth.token_store, {s.value for s in TokenStore}),
        ("auth.jwt_algorithm", auth.jwt_algorithm, {a.value for a in JwtAlgorithm}),
        ("auth.deletion_mode", auth.deletion_mode, {"soft", "hard"}),
        ("auth.provider", auth.provider, {p.value for p in AuthProvider}),
    ):
        if value not in allowed:
            ctx.add(path, "invalid_value", f"must be one of {', '.join(sorted(allowed))}")
    if auth.sms_provider is not None and auth.sms_provider not in {p.value for p in SmsProvider}:
        ctx.add("auth.sms_provider", "invalid_value", "must be twilio, aws_sns or vonage")
    valid_types = {t.value for t in AuthCustomFieldType}
    for i, f in enumerate(auth.registration.custom_fields):
        if f.type not in valid_types:
            ctx.add(
                f"auth.registration.custom_fields[{i}].type",
                "invalid_value",
                f"must be one of {', '.join(sorted(valid_types))}",
            )
    _check_auth_permissions(auth, entities, ctx)


def _check_auth_permissions(auth: SpecAuth, entities: dict[str, SpecEntity], ctx: _Ctx) -> None:
    operations = {o.value for o in AuthOperation}
    row_rules = {r.value for r in RowRule}
    role_names = {r.name for r in auth.roles}
    seen: set[tuple[str, str]] = set()
    for i, perm in enumerate(auth.permissions):
        p = f"auth.permissions[{i}]"
        if perm.entity not in entities:
            ctx.add(f"{p}.entity", "unknown_entity", f"no entity named {perm.entity[:40]!r}")
        if perm.operation not in operations:
            ctx.add(
                f"{p}.operation", "invalid_value", f"must be one of {', '.join(sorted(operations))}"
            )
        elif (perm.entity, perm.operation) in seen:
            ctx.add(p, "duplicate_name", "each entity and operation may appear only once")
        seen.add((perm.entity, perm.operation))
        for role in perm.roles:
            if role not in role_names:
                ctx.add(f"{p}.roles", "unknown_reference", f"role {role[:40]!r} does not exist")
        if perm.row_rule is not None and perm.row_rule not in row_rules:
            ctx.add(
                f"{p}.row_rule", "invalid_value", f"must be one of {', '.join(sorted(row_rules))}"
            )
        custom = perm.row_rule == RowRule.custom_filter
        has_filter = perm.custom_filter_field is not None or perm.custom_filter_value is not None
        if custom and (perm.custom_filter_field is None or perm.custom_filter_value is None):
            ctx.add(
                p, "required", "custom_filter needs custom_filter_field and custom_filter_value"
            )
        elif has_filter and not custom:
            ctx.add(
                p,
                "not_applicable",
                "custom filter values are only valid for row_rule custom_filter",
            )


def invitations_enabled(auth: SpecAuth) -> bool:
    """Invitations exist when registration is invite-only, any role is granted by invite, or
    tenants are in use (a new user joins an existing tenant through an invitation)."""
    return (
        auth.registration.invite_only or auth.multi_tenant or any(r.invite_only for r in auth.roles)
    )


def _check_auth_tenancy(auth: SpecAuth, ctx: _Ctx) -> None:
    if auth.multi_tenant and auth.registration.invite_only:
        ctx.add(
            "auth.multi_tenant",
            "invalid_value",
            "with multi-tenancy, open sign-up creates a tenant and invitations join one; "
            "invite-only registration would leave no way to create the first tenant",
        )
    if auth.multi_tenant and ADMIN_ROLE not in {r.name for r in auth.roles}:
        ctx.add(
            "auth.multi_tenant",
            "unknown_reference",
            f"the user who creates a tenant becomes its {ADMIN_ROLE!r}, so a role with that "
            "name must exist",
        )
    if not auth.multi_tenant:
        for i, perm in enumerate(auth.permissions):
            if perm.row_rule == RowRule.tenant:
                ctx.add(
                    f"auth.permissions[{i}].row_rule",
                    "invalid_value",
                    "the tenant row rule needs multi_tenant to be switched on",
                )


def _check_auth_invitations(auth: SpecAuth, ctx: _Ctx) -> None:
    for i, role in enumerate(auth.roles):
        if role.invite_only and (role.is_default or role.self_assignable):
            ctx.add(
                f"auth.roles[{i}]",
                "invalid_value",
                "an invite-only role cannot also be a default or self-assignable role",
            )
    if not invitations_enabled(auth):
        return
    where = "auth.roles"
    if auth.multi_tenant:
        where = "auth.multi_tenant"
    elif auth.registration.invite_only:
        where = "auth.registration.invite_only"
    if auth.smtp is None:
        ctx.add(where, "required", "invitations are sent by email, so smtp must be configured")
    if auth.app_url is None:
        ctx.add(where, "required", "app_url is needed to build the link in invitation emails")
    if ADMIN_ROLE not in {r.name for r in auth.roles}:
        ctx.add(
            where,
            "unknown_reference",
            f"only the {ADMIN_ROLE!r} role can send invitations, so a role named "
            f"{ADMIN_ROLE!r} must exist",
        )


# Entity field types a custom_filter row rule can compare with a plain `==`.
_FILTERABLE_TYPES = {"string", "enum", "integer", "bigint", "boolean"}
ADMIN_ROLE = "admin"
# "fk_" + table + "_created_by_id_auth_users" (and the tenant one) must stay within the
# 63 characters Postgres allows for a name.
_MAX_OWNED_TABLE = 35


def _check_auth_permission_rules(
    auth: SpecAuth, entities: dict[str, SpecEntity], ctx: _Ctx
) -> None:
    role_names = {r.name for r in auth.roles}
    for i, perm in enumerate(auth.permissions):
        p = f"auth.permissions[{i}]"
        if perm.row_rule == RowRule.role_scoped and ADMIN_ROLE not in role_names:
            ctx.add(
                f"{p}.row_rule",
                "unknown_reference",
                f"role_scoped lets the {ADMIN_ROLE!r} role see every row, so a role "
                f"named {ADMIN_ROLE!r} must exist",
            )
        owner_rule = perm.row_rule in (RowRule.owner, RowRule.role_scoped, RowRule.tenant)
        owned_entity = entities.get(perm.entity)
        if (
            owner_rule
            and owned_entity is not None
            and len(owned_entity.table_name) > _MAX_OWNED_TABLE
        ):
            ctx.add(
                f"{p}.entity",
                "identifier_too_long",
                f"{owned_entity.table_name!r} gets a created_by_id foreign key whose generated "
                f"name must fit 63 characters, so the table name can be at most "
                f"{_MAX_OWNED_TABLE} characters",
            )
        injected = {
            RowRule.owner: "created_by_id",
            RowRule.role_scoped: "created_by_id",
            RowRule.tenant: "tenant_id",
        }.get(perm.row_rule)  # type: ignore[call-overload]
        if (
            injected
            and owned_entity is not None
            and any(f.name == injected for f in owned_entity.fields)
        ):
            ctx.add(
                f"{p}.entity",
                "reserved_name",
                f"the {perm.row_rule} rule adds a {injected!r} column to "
                f"{owned_entity.name}, which already has a field of that name",
            )
        if perm.row_rule != RowRule.custom_filter:
            continue
        entity = entities.get(perm.entity)
        if entity is None or perm.custom_filter_field is None or perm.custom_filter_value is None:
            continue  # reported by the structural checks
        field = next((f for f in entity.fields if f.name == perm.custom_filter_field), None)
        if field is None:
            ctx.add(
                f"{p}.custom_filter_field",
                "unknown_field",
                f"{entity.name} has no field {perm.custom_filter_field[:40]!r}",
            )
        elif field.type not in _FILTERABLE_TYPES:
            ctx.add(
                f"{p}.custom_filter_field",
                "unsupported_value",
                f"a custom filter can compare string, enum, integer and boolean fields, "
                f"not {field.type}",
            )
        elif not _filter_value_ok(field, perm.custom_filter_value):
            ctx.add(
                f"{p}.custom_filter_value",
                "invalid_value",
                f"{perm.custom_filter_value[:40]!r} is not a valid {field.type} value",
            )


def _filter_value_ok(field: SpecField, value: str) -> bool:
    match field.type:
        case "integer" | "bigint":
            try:
                int(value)
            except ValueError:
                return False
            return True
        case "boolean":
            return value in ("true", "false")
        case "enum":
            return value in (field.enum_values or [])
        case _:
            return len(value) <= MAX_STRING_LENGTH and not _CONTROL_CHARS_RE.search(value)


def _check_auth_email_sms(auth: SpecAuth, ctx: _Ctx) -> None:
    reset = auth.password_reset
    if (reset.email_magic_link or auth.registration.email_verification_required) and not auth.smtp:
        ctx.add(
            "auth.smtp",
            "required",
            "smtp is required when email magic links or email verification are enabled",
        )
    _check_smtp_shape(auth, ctx)
    _check_sms(auth, ctx)


def _check_smtp_shape(auth: SpecAuth, ctx: _Ctx) -> None:
    if auth.smtp is not None:
        smtp = auth.smtp
        if not _HOST_RE.fullmatch(smtp.host):
            ctx.add("auth.smtp.host", "invalid_value", "must be a host name or IP address")
        if not 1 <= smtp.port <= 65535:
            ctx.add("auth.smtp.port", "out_of_range", "must be between 1 and 65535")
        if len(smtp.from_email) > 255 or not _EMAIL_RE.fullmatch(smtp.from_email):
            ctx.add("auth.smtp.from_email", "invalid_value", "must be an email address")
        if not _single_line(smtp.from_name):
            ctx.add("auth.smtp.from_name", "invalid_value", "must be a single non-blank line")


def _check_sms(auth: SpecAuth, ctx: _Ctx) -> None:
    reset = auth.password_reset
    if reset.sms_otp:
        if auth.sms_provider is None:
            ctx.add("auth.sms_provider", "required", "required when sms_otp is enabled")
        if auth.sms is None:
            ctx.add("auth.sms", "required", "required when sms_otp is enabled")
    if auth.sms is not None:
        sender = auth.sms.from_number
        if auth.sms_provider == SmsProvider.aws_sns:
            valid = bool(_SMS_SENDER_ID_RE.fullmatch(sender) or _PHONE_E164_RE.fullmatch(sender))
            hint = "an E.164 number or an alphanumeric sender id (max 11 characters)"
        else:
            valid = bool(_PHONE_E164_RE.fullmatch(sender))
            hint = "an E.164 number such as +14155550123"
        if not valid:
            ctx.add("auth.sms.from_number", "invalid_value", f"must be {hint}")


def _check_auth_branding(auth: SpecAuth, ctx: _Ctx) -> None:
    _check_branding_shape(auth, ctx)
    needs_links = (
        auth.password_reset.email_magic_link or auth.registration.email_verification_required
    )
    if needs_links and auth.app_url is None:
        ctx.add(
            "auth.app_url",
            "required",
            "app_url is required to build the links in verification and magic link emails",
        )


def _check_branding_shape(auth: SpecAuth, ctx: _Ctx) -> None:
    if auth.app_name is not None and not _single_line(auth.app_name):
        ctx.add("auth.app_name", "invalid_value", "must be a single non-blank line")
    if auth.app_url is not None and (
        len(auth.app_url) > 2000 or not _URL_RE.fullmatch(auth.app_url)
    ):
        ctx.add("auth.app_url", "invalid_value", "must be an http(s) URL")


def _check_auth_roles(auth: SpecAuth, ctx: _Ctx) -> None:
    if len(auth.roles) > _MAX_ROLES:
        ctx.add("auth.roles", "too_many", f"at most {_MAX_ROLES} roles are allowed")
    names: set[str] = set()
    for i, role in enumerate(auth.roles):
        p = f"auth.roles[{i}]"
        ok = _identifier(ctx, f"{p}.name", role.name, naming.SNAKE_NAME_RE, sql=False, python=False)
        if ok and role.name in names:
            ctx.add(f"{p}.name", "duplicate_name", f"role {role.name!r} is already defined")
        names.add(role.name)
        if not _single_line(role.label):
            ctx.add(f"{p}.label", "invalid_value", "must be a single non-blank line")
    parents = {r.name: r.inherits_from for r in auth.roles}
    for i, role in enumerate(auth.roles):
        if role.inherits_from is None:
            continue
        p = f"auth.roles[{i}].inherits_from"
        if role.inherits_from not in names:
            ctx.add(p, "unknown_reference", f"role {role.inherits_from[:40]!r} does not exist")
            continue
        seen = {role.name}
        cursor: str | None = role.inherits_from
        while cursor is not None:
            if cursor in seen:
                ctx.add(p, "cycle", "role inheritance must not form a cycle")
                break
            seen.add(cursor)
            cursor = parents.get(cursor)


def _check_auth_custom_fields(auth: SpecAuth, ctx: _Ctx) -> None:
    fields = auth.registration.custom_fields
    if len(fields) > _MAX_CUSTOM_FIELDS:
        ctx.add(
            "auth.registration.custom_fields",
            "too_many",
            f"at most {_MAX_CUSTOM_FIELDS} custom fields are allowed",
        )
    seen: set[str] = set()
    valid_types = {t.value for t in AuthCustomFieldType}
    for i, f in enumerate(fields):
        p = f"auth.registration.custom_fields[{i}]"
        name_ok = _identifier(
            ctx, f"{p}.name", f.name, naming.SNAKE_NAME_RE, sql=True, attribute=True
        )
        if name_ok and f.name in AUTH_USER_COLUMNS:
            ctx.add(f"{p}.name", "reserved_name", f"{f.name!r} is a built-in column of auth_users")
        elif name_ok and f.name in seen:
            ctx.add(f"{p}.name", "duplicate_name", f"custom field {f.name!r} is already defined")
        seen.add(f.name)
        if not _single_line(f.label):
            ctx.add(f"{p}.label", "invalid_value", "must be a single non-blank line")
        if f.type not in valid_types:
            continue  # reported by _check_auth_structure
        _check_custom_field_constraints(f, p, ctx)


def _check_custom_field_constraints(f: SpecAuthCustomField, p: str, ctx: _Ctx) -> None:
    if f.type == "enum":
        values = f.enum_values or []
        if not values:
            ctx.add(f"{p}.enum_values", "required", "enum fields need at least one value")
        elif len(values) > _MAX_AUTH_ENUM_VALUES or len(set(values)) != len(values):
            ctx.add(f"{p}.enum_values", "invalid_value", "values must be unique, at most 50")
        elif not all(_ENUM_VALUE_RE.fullmatch(v) for v in values):
            ctx.add(f"{p}.enum_values", "invalid_value", "values must match [A-Za-z0-9_.-]{1,64}")
    elif f.enum_values:
        ctx.add(f"{p}.enum_values", "not_applicable", "only valid for enum fields")
    for attr in ("min_length", "max_length"):
        length = getattr(f, attr)
        if length is None:
            continue
        if f.type not in _TEXT_LIKE:
            ctx.add(f"{p}.{attr}", "not_applicable", "only valid for text-like fields")
        elif not 0 <= length <= MAX_STRING_LENGTH:
            ctx.add(f"{p}.{attr}", "out_of_range", f"must be between 0 and {MAX_STRING_LENGTH}")
    if f.min_length is not None and f.max_length is not None and f.min_length > f.max_length:
        ctx.add(f"{p}.min_length", "invalid_range", "min_length must not exceed max_length")
    for attr in ("min_value", "max_value"):
        bound = getattr(f, attr)
        if bound is None:
            continue
        if f.type not in ("integer", "float"):
            ctx.add(f"{p}.{attr}", "not_applicable", "only valid for integer and float fields")
        elif not math.isfinite(bound):
            ctx.add(f"{p}.{attr}", "invalid_value", "must be a finite number")
    if (
        f.min_value is not None
        and f.max_value is not None
        and math.isfinite(f.min_value)
        and math.isfinite(f.max_value)
        and f.min_value > f.max_value
    ):
        ctx.add(f"{p}.min_value", "invalid_range", "min_value must not exceed max_value")
    if f.default_value is not None:
        _check_custom_default(f, p, ctx)


def _check_custom_default(f: SpecAuthCustomField, p: str, ctx: _Ctx) -> None:
    value = f.default_value or ""
    try:
        match f.type:
            case "integer":
                int(value)
            case "float":
                if not math.isfinite(float(value)):
                    raise ValueError(value)
            case "boolean":
                if value not in ("true", "false"):
                    raise ValueError(value)
            case "date":
                date.fromisoformat(value)
            case "datetime":
                datetime.fromisoformat(value)
            case "enum":
                if value not in (f.enum_values or []):
                    raise ValueError(value)
            case _:
                if len(value) > MAX_STRING_LENGTH or _CONTROL_CHARS_RE.search(value):
                    raise ValueError(value)
    except ValueError:
        ctx.add(
            f"{p}.default_value",
            "invalid_default",
            f"{value[:40]!r} is not a valid default for type {f.type}",
        )


# --- keycloak ---------------------------------------------------------------------------

_REALM_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_CLIENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_ALIAS_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")
_DOMAIN_RE = re.compile(
    r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)
_RESERVED_REALMS = frozenset({"master"})
_MAX_REDIRECT_URIS = 20
_MAX_IDENTITY_PROVIDERS = 10
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_OIDC_ENDPOINTS = ("issuer", "authorization_url", "token_url", "jwks_url", "userinfo_url")
_OIDC_REQUIRED_ENDPOINTS = ("issuer", "authorization_url", "token_url", "jwks_url")
_URL_FORBIDDEN_RE = re.compile(r"[\s\"'<>\\*`]")


def redirect_uri_problem(uri: str) -> str | None:
    """Why `uri` is unsafe as an OAuth redirect URI, or None. Redirect URIs are exact: no
    wildcards, no embedded credentials, no fragment, https except for local development."""
    if len(uri) > 2000 or _URL_FORBIDDEN_RE.search(uri) or _CONTROL_CHARS_RE.search(uri):
        return "must be a plain URL without spaces, quotes, backslashes or wildcards"
    try:
        parts = urlsplit(uri)
        port = parts.port  # raises for an invalid port
    except ValueError:
        return "is not a valid URL"
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return "must be an absolute http(s) URL"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "must not contain credentials"
    if parts.fragment or "#" in uri:
        return "must not contain a fragment"
    if port is not None and not 1 <= port <= 65535:
        return "has an invalid port"
    if parts.scheme == "http" and host not in _LOCAL_HOSTS:
        return "must use https (http is only allowed for localhost)"
    return None


def _check_auth_keycloak(auth: SpecAuth, entities: dict[str, SpecEntity], ctx: _Ctx) -> None:
    """Rules for a project whose users and tokens come from Keycloak."""
    kc = auth.keycloak
    if kc is None:
        ctx.add("auth.keycloak", "required", "Keycloak is selected, so its settings are required")
    else:
        _check_keycloak_block(kc, ctx)
    _check_keycloak_exclusions(auth, ctx)

    if not 1 <= auth.access_token_ttl_minutes <= 1440:
        ctx.add("auth.access_token_ttl_minutes", "out_of_range", "must be between 1 and 1440")
    _check_smtp_shape(auth, ctx)
    if auth.registration.email_verification_required and auth.smtp is None:
        ctx.add(
            "auth.smtp",
            "required",
            "smtp is required when email verification is enabled (Keycloak sends the mail)",
        )
    _check_branding_shape(auth, ctx)
    _check_auth_roles(auth, ctx)
    _check_auth_permission_rules(auth, entities, ctx)


# Names a custom field may not take with Keycloak: its own profile attributes and the claims
# a token already carries (a field is delivered to the API as a claim of the same name).
KEYCLOAK_RESERVED_FIELD_NAMES = frozenset(
    {
        "username",
        "firstName",
        "lastName",
        "name",
        "sub",
        "iss",
        "aud",
        "exp",
        "iat",
        "nbf",
        "jti",
        "typ",
        "azp",
        "sid",
        "acr",
        "scope",
        "email_verified",
        "given_name",
        "family_name",
        "preferred_username",
        "resource_access",
        "realm_access",
        "organization",
        "auth_time",
        "session_state",
        "allowed_origins",
    }
)


def _check_keycloak_custom_fields(auth: SpecAuth, ctx: _Ctx) -> None:
    """Custom registration fields become Keycloak user attributes, delivered as token claims."""
    _check_auth_custom_fields(auth, ctx)
    for i, f in enumerate(auth.registration.custom_fields):
        p = f"auth.registration.custom_fields[{i}]"
        if f.name in KEYCLOAK_RESERVED_FIELD_NAMES:
            ctx.add(
                f"{p}.name",
                "reserved_name",
                f"{f.name!r} is already a Keycloak user attribute or token claim",
            )
        if f.unique:
            ctx.add(
                f"{p}.unique",
                "unsupported_value",
                "Keycloak cannot keep a custom attribute unique across users; turn unique off",
            )


def _check_keycloak_exclusions(auth: SpecAuth, ctx: _Ctx) -> None:
    """What does not exist with Keycloak. Each is rejected rather than ignored, so nothing the
    user configured silently disappears."""
    if not auth.multi_tenant:
        for i, perm in enumerate(auth.permissions):
            if perm.row_rule == RowRule.tenant:
                ctx.add(
                    f"auth.permissions[{i}].row_rule",
                    "invalid_value",
                    "the tenant row rule needs multi_tenant to be switched on",
                )
    _check_keycloak_custom_fields(auth, ctx)
    if auth.password_reset.sms_otp:
        ctx.add(
            "auth.password_reset.sms_otp",
            "unsupported_value",
            "SMS one-time codes are not available with Keycloak; turn them off",
        )
    for i, role in enumerate(auth.roles):
        if role.self_assignable:
            ctx.add(
                f"auth.roles[{i}].self_assignable",
                "unsupported_value",
                "with Keycloak, roles are granted in Keycloak, not chosen at sign-up; "
                "turn off self-assignable",
            )
        if role.invite_only:
            ctx.add(
                f"auth.roles[{i}].invite_only",
                "unsupported_value",
                "invitations do not exist with Keycloak; create the user in Keycloak instead",
            )


def _check_keycloak_block(kc: SpecKeycloak, ctx: _Ctx) -> None:
    p = "auth.keycloak"
    if kc.mode not in {m.value for m in KeycloakMode}:
        ctx.add(f"{p}.mode", "invalid_value", "must be own or shared")
    if kc.mfa not in {m.value for m in MfaMode}:
        ctx.add(f"{p}.mfa", "invalid_value", "must be off, optional or required")
    if not _REALM_RE.fullmatch(kc.realm):
        ctx.add(
            f"{p}.realm",
            "invalid_identifier",
            "must be lowercase letters, digits and hyphens, at most 63 characters",
        )
    elif kc.realm in _RESERVED_REALMS:
        ctx.add(f"{p}.realm", "reserved_name", f"{kc.realm!r} is Keycloak's admin realm")
    for name, value in (("api_client_id", kc.api_client_id), ("web_client_id", kc.web_client_id)):
        if not _CLIENT_ID_RE.fullmatch(value):
            ctx.add(
                f"{p}.{name}",
                "invalid_identifier",
                "must start with a letter or digit and use letters, digits, . _ - (at most 100)",
            )
    if kc.api_client_id == kc.web_client_id:
        ctx.add(f"{p}.web_client_id", "duplicate_name", "must differ from api_client_id")

    bounds = (
        ("password_min_length", kc.password_min_length, 8, 128),
        ("session_idle_minutes", kc.session_idle_minutes, 5, 43_200),
        ("session_max_hours", kc.session_max_hours, 1, 720),
        ("audit_retention_days", kc.audit_retention_days, 7, 3650),
    )
    for bound_name, number, low, high in bounds:
        if not low <= number <= high:
            ctx.add(f"{p}.{bound_name}", "out_of_range", f"must be between {low} and {high}")
    if kc.session_idle_minutes > kc.session_max_hours * 60:
        ctx.add(
            f"{p}.session_idle_minutes",
            "invalid_range",
            "the idle timeout must not exceed the maximum session length",
        )

    if not kc.redirect_uris:
        ctx.add(
            f"{p}.redirect_uris",
            "required",
            "add at least one redirect URL, the address people return to after signing in "
            "(for local work: http://localhost:3000/)",
        )
    if len(kc.redirect_uris) > _MAX_REDIRECT_URIS:
        ctx.add(f"{p}.redirect_uris", "too_many", f"at most {_MAX_REDIRECT_URIS} are allowed")
    seen_uris: set[str] = set()
    for i, uri in enumerate(kc.redirect_uris):
        problem = redirect_uri_problem(uri)
        if problem:
            ctx.add(f"{p}.redirect_uris[{i}]", "invalid_value", problem)
        elif uri in seen_uris:
            ctx.add(f"{p}.redirect_uris[{i}]", "duplicate_name", "is listed twice")
        seen_uris.add(uri)

    _check_identity_providers(kc, ctx)


def _check_identity_providers(kc: SpecKeycloak, ctx: _Ctx) -> None:
    p = "auth.keycloak.identity_providers"
    providers = kc.identity_providers
    if providers and kc.mode == KeycloakMode.shared:
        ctx.add(
            p,
            "not_applicable",
            "a shared realm's logins are configured in the project that runs Keycloak; "
            "set them there",
        )
        return
    if len(providers) > _MAX_IDENTITY_PROVIDERS:
        ctx.add(p, "too_many", f"at most {_MAX_IDENTITY_PROVIDERS} are allowed")
    aliases: set[str] = set()
    types = {t.value for t in IdpType}
    for i, idp in enumerate(providers):
        q = f"{p}[{i}]"
        if not _ALIAS_RE.fullmatch(idp.alias):
            ctx.add(
                f"{q}.alias",
                "invalid_identifier",
                "must start with a lowercase letter and use lowercase letters, digits, hyphens "
                "(at most 31)",
            )
        elif idp.alias in aliases:
            ctx.add(f"{q}.alias", "duplicate_name", f"alias {idp.alias!r} is already used")
        aliases.add(idp.alias)
        if idp.display_name is not None and not _single_line(idp.display_name):
            ctx.add(f"{q}.display_name", "invalid_value", "must be a single non-blank line")
        if (
            not idp.client_id.strip()
            or len(idp.client_id) > 255
            or _CONTROL_CHARS_RE.search(idp.client_id)
            or any(c.isspace() for c in idp.client_id)
        ):
            ctx.add(
                f"{q}.client_id", "invalid_value", "must be the id from the provider, no spaces"
            )
        if idp.type not in types:
            ctx.add(f"{q}.type", "invalid_value", f"must be one of {', '.join(sorted(types))}")
            continue
        _check_identity_provider_extras(idp.type, idp, q, ctx)


def _check_identity_provider_extras(kind: str, idp: Any, q: str, ctx: _Ctx) -> None:
    allowed = {
        IdpType.google: {"hosted_domain"},
        IdpType.microsoft: {"tenant_id"},
        IdpType.github: set(),
        IdpType.oidc: set(_OIDC_ENDPOINTS),
    }[IdpType(kind)]
    for name in ("tenant_id", "hosted_domain", *_OIDC_ENDPOINTS):
        if name not in allowed and getattr(idp, name) is not None:
            ctx.add(f"{q}.{name}", "not_applicable", f"does not apply to {kind} logins")
    if kind == IdpType.microsoft:
        tenant = idp.tenant_id
        try:
            valid = tenant is not None and str(uuid.UUID(tenant)) == tenant.lower()
        except ValueError:
            valid = False
        if not valid:
            ctx.add(
                f"{q}.tenant_id",
                "required",
                "Microsoft Entra ID needs your directory (tenant) id, a GUID like "
                "00000000-0000-0000-0000-000000000000; common and organizations tenants are not "
                "accepted because they let any Microsoft account in",
            )
    domain = idp.hosted_domain
    bad_domain = domain is not None and (len(domain) > 255 or not _DOMAIN_RE.fullmatch(domain))
    if kind == IdpType.google and bad_domain:
        ctx.add(f"{q}.hosted_domain", "invalid_value", "must be a domain such as example.com")
    if kind == IdpType.oidc:
        for name in _OIDC_ENDPOINTS:
            url = getattr(idp, name)
            if url is None:
                if name in _OIDC_REQUIRED_ENDPOINTS:
                    ctx.add(f"{q}.{name}", "required", "required for a generic OIDC login")
            elif not url.startswith("https://") or redirect_uri_problem(url) is not None:
                ctx.add(f"{q}.{name}", "invalid_value", "must be an https URL")
