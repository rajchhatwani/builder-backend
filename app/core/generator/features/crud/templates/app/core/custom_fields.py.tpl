"""Validation of per-row custom fields (generated).

Values are checked against the definitions declared in the spec: unknown keys are rejected, types are
strict (a string is not an int, a bool is not an int), required keys must be present, and the number of
keys and the encoded size are capped. Dates and datetimes are stored as ISO strings. Raises ValueError
(a 422 through Pydantic); the message names the key, never the value.
"""

import datetime as dt
import json
from typing import Any

INT_MIN = -(2**31)
INT_MAX = 2**31 - 1
DEFAULT_STRING_LENGTH = 255

# (name, type, required, max_length, enum_values)
Definition = tuple[str, str, bool, int | None, tuple[str, ...] | None]


def _string(name: str, value: Any, max_length: int | None, enum_values: tuple[str, ...] | None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"custom field {name!r} must be a string")
    if enum_values is not None and value not in enum_values:
        raise ValueError(f"custom field {name!r} must be one of {list(enum_values)}")
    if len(value) > (max_length or DEFAULT_STRING_LENGTH):
        raise ValueError(f"custom field {name!r} is longer than {max_length or DEFAULT_STRING_LENGTH}")
    return value


def _date(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"custom field {name!r} must be an ISO date string")
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"custom field {name!r} must be an ISO date (YYYY-MM-DD)") from None


def _datetime(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"custom field {name!r} must be an ISO datetime string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"custom field {name!r} must be an ISO datetime") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.isoformat()


def _coerce(definition: Definition, value: Any) -> Any:
    name, kind, _required, max_length, enum_values = definition
    if kind == "string":
        return _string(name, value, max_length, enum_values)
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or not INT_MIN <= value <= INT_MAX:
            raise ValueError(f"custom field {name!r} must be a 32-bit integer")
        return value
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, int | float) or value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"custom field {name!r} must be a finite number")
        try:
            return float(value)
        except OverflowError:
            raise ValueError(f"custom field {name!r} must be a finite number") from None
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"custom field {name!r} must be true or false")
        return value
    if kind == "date":
        return _date(name, value)
    if kind == "datetime":
        return _datetime(name, value)
    raise ValueError(f"custom field {name!r} has an unknown type")


def validate(
    value: dict[str, Any], definitions: tuple[Definition, ...], *, max_keys: int, max_bytes: int
) -> dict[str, Any]:
    """The cleaned dict to store. Null values count as absent."""
    if len(value) > max_keys:
        raise ValueError(f"at most {max_keys} custom fields are allowed")
    by_name = {d[0]: d for d in definitions}
    unknown = sorted(set(value) - set(by_name))
    if unknown:
        raise ValueError(f"unknown custom field(s): {unknown}")
    clean: dict[str, Any] = {}
    for name, raw in value.items():
        if raw is not None:
            clean[name] = _coerce(by_name[name], raw)
    missing = sorted(d[0] for d in definitions if d[2] and d[0] not in clean)
    if missing:
        raise ValueError(f"missing required custom field(s): {missing}")
    if len(json.dumps(clean, separators=(",", ":")).encode()) > max_bytes:
        raise ValueError(f"custom fields are larger than {max_bytes} bytes")
    return clean
