"""Pure identifier helpers. No FastAPI or DB imports (see PLAN.md section 5).

Two groups: deterministic derivation rules (defaults for table_name/plural_path/slug and
the names generated from relations) and the identifier rules that `validation` enforces.
"""

import builtins
import keyword
import re

_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")


def to_snake_case(name: str) -> str:
    return _CAMEL_BOUNDARY_RE.sub("_", name).lower()


def pluralize(word: str) -> str:
    lower = word.lower()
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lower.endswith("y") and len(word) > 1 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def slugify(name: str) -> str:
    slug = _SLUG_INVALID_RE.sub("-", name.lower()).strip("-")
    return slug or "project"


# --- identifier rules (enforced by validation.validate) ---------------------------------

MAX_IDENTIFIER_LENGTH = 63  # Postgres truncates identifiers longer than this
ENTITY_NAME_RE = re.compile(r"[A-Z][A-Za-z0-9]*")
SNAKE_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
SLUG_RE = re.compile(r"[a-z][a-z0-9-]*")
AUTO_FIELDS = {"id": "uuid", "created_at": "datetime", "updated_at": "datetime"}
SOFT_DELETE_FIELD = ("deleted_at", "datetime")

_PYTHON_RESERVED = (
    frozenset(keyword.kwlist) | frozenset(keyword.softkwlist) | frozenset(dir(builtins))
)

# PostgreSQL "reserved" keywords (SQL Key Words appendix): they cannot be used as
# unquoted table or column names, and generated code never quotes identifiers.
_SQL_RESERVED = frozenset(
    """
    all analyse analyze and any array as asc asymmetric authorization binary both case cast
    check collate collation column concurrently constraint create cross current_catalog
    current_date current_role current_schema current_time current_timestamp current_user
    default deferrable desc distinct do else end except false fetch for foreign freeze from
    full grant group having ilike in initially inner intersect into is isnull join lateral
    leading left like limit localtime localtimestamp natural not notnull null offset on only
    or order outer overlaps placing primary references returning right select session_user
    similar some symmetric system_user table tablesample then to trailing true union unique
    user using variadic verbose when where window with
    """.split()  # noqa: SIM905
)

# Names the generated app already serves at the root, plus the migration bookkeeping table.
RESERVED_PATHS = frozenset({"health", "ready", "docs", "redoc"})
RESERVED_TABLES = frozenset({"alembic_version"})


def is_python_reserved(name: str) -> bool:
    return name in _PYTHON_RESERVED


def is_sql_reserved(name: str) -> bool:
    return name.lower() in _SQL_RESERVED


def fk_column_name(relation_name: str) -> str:
    """Column added to the `to` entity for one_to_many / one_to_one relations."""
    return f"{relation_name}_id"


def join_table_name(from_table: str, from_name: str) -> str:
    """Join table for a many_to_many relation; unique because from_name is per-entity unique."""
    return f"{from_table}_{from_name}"


# Attribute names the generated code cannot safely use: SQLAlchemy's declarative base and
# Pydantic's BaseModel own these, and `model_` is Pydantic's protected prefix.
RESERVED_ATTRIBUTES = frozenset(
    {
        "metadata",
        "registry",
        "copy",
        "json",
        "schema",
        "validate",
        "construct",
        "fields",
        "parse_obj",
        "parse_raw",
        "parse_file",
        "from_orm",
        "schema_json",
        "update_forward_refs",
    }
)
RESERVED_ATTRIBUTE_PREFIXES = ("model_",)

# Query parameters the generated list endpoints define themselves.
RESERVED_QUERY_PARAMS = frozenset({"limit", "offset", "sort", "q"})


def is_reserved_attribute(name: str) -> bool:
    return name in RESERVED_ATTRIBUTES or name.startswith(RESERVED_ATTRIBUTE_PREFIXES)
