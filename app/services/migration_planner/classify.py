# ruff: noqa: E501
"""Safety classification of one column / constraint change."""

from .diff import Col
from .model import Safety

_INTS = {"integer", "bigint"}
_NUMERIC_TARGETS = {"integer", "bigint", "float", "decimal"}
# (old, new) pairs that never lose a value: widening, or rendering to text.
_LOSSLESS = {
    ("integer", "bigint"),
    ("integer", "decimal"),
    ("integer", "float"),
    ("bigint", "decimal"),
    ("float", "decimal"),
    ("string", "text"),
    ("uuid", "string"),
    ("uuid", "text"),
}
_TO_TEXT_OK = {"integer", "bigint", "float", "decimal", "boolean", "date", "datetime", "uuid", "enum"}
# text-ish source parsed into a typed column: needs a cast, existing rows may not parse.
_CASTABLE_FROM_TEXT = {"integer", "bigint", "float", "decimal", "boolean", "date", "datetime", "uuid"}

PG_TYPES = {
    "string": "varchar",
    "text": "text",
    "integer": "integer",
    "bigint": "bigint",
    "float": "double precision",
    "decimal": "numeric",
    "boolean": "boolean",
    "date": "date",
    "datetime": "timestamptz",
    "uuid": "uuid",
    "json": "jsonb",
    "enum": "varchar",
    "file": "uuid",
}


def pg_type(c: Col) -> str:
    base = PG_TYPES[c.type]
    if c.type == "string" and c.max_length:
        return f"varchar({c.max_length})"
    return base


def type_change(old: Col, new: Col) -> tuple[str, Safety, str]:
    """-> (kind, safety, reason). Only called when old.type != new.type."""
    pair = (old.type, new.type)
    if pair in _LOSSLESS or (new.type in {"string", "text"} and old.type in _TO_TEXT_OK):
        return "widen_type", Safety.safe, f"{old.type} -> {new.type} keeps every value"
    if old.type in {"string", "text"} and new.type in _CASTABLE_FROM_TEXT:
        return "convert_type", Safety.backfill, f"{old.type} -> {new.type} needs a cast; existing rows may not parse"
    if old.type == "text" and new.type == "string":
        return "narrow_type", Safety.destructive, "text -> string can truncate long values"
    if pair in {("bigint", "integer"), ("decimal", "integer"), ("decimal", "bigint"), ("float", "integer"), ("float", "bigint"), ("decimal", "float")}:
        return "narrow_type", Safety.destructive, f"{old.type} -> {new.type} can overflow or lose precision"
    if old.type == "enum" and new.type == "enum":
        raise AssertionError("enum->enum is not a type change")
    return "change_type", Safety.destructive, f"{old.type} -> {new.type} is not a compatible conversion"


def length_change(old: Col, new: Col) -> tuple[str, Safety, str] | None:
    """Only for string columns. None means unchanged. None max_length = unbounded."""
    if old.max_length == new.max_length:
        return None
    if new.max_length is None or (old.max_length is not None and new.max_length > old.max_length):
        return "widen_type", Safety.safe, f"length {old.max_length} -> {new.max_length} only grows"
    return "shorten_length", Safety.destructive, f"length {old.max_length} -> {new.max_length} can truncate values"


def enum_change(old: Col, new: Col) -> tuple[list[str], list[str]]:
    o, n = set(old.enum_values or ()), set(new.enum_values or ())
    return sorted(n - o), sorted(o - n)


def is_unbounded(c: Col) -> bool:
    return c.max_length is None


def has_default(c: Col) -> bool:
    return c.default is not None


def literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"
