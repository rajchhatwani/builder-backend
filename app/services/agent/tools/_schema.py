"""A small JSON-schema checker for the subset the tool schemas use (type, properties, required,
additionalProperties, enum, min/maxLength, pattern, minimum, items, maxItems). No extra dependency."""

import re
from typing import Any

_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "boolean": bool,
    "number": (int, float),
}


def _type_ok(value: Any, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def validate(value: Any, schema: dict[str, Any], path: str = "") -> list[tuple[str, str]]:
    """(location, message) for every violation; empty = valid."""
    here = path or "<input>"
    t = schema.get("type")
    if t is not None and not _type_ok(value, t):
        return [(here, f"expected {t}")]
    out: list[tuple[str, str]] = []
    if "enum" in schema and value not in schema["enum"]:
        out.append((here, f"must be one of {schema['enum']}"))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append((here, "too short"))
        if len(value) > schema.get("maxLength", 10**9):
            out.append((here, "too long"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append((here, "does not match the required pattern"))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value < schema.get("minimum", value):
        out.append((here, f"must be >= {schema['minimum']}"))
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10**9):
            out.append((here, "too many items"))
        if "items" in schema:
            for i, v in enumerate(value):
                out.extend(validate(v, schema["items"], f"{path}[{i}]"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append((f"{path}.{key}".lstrip("."), "required"))
        for key, v in value.items():
            sub = f"{path}.{key}".lstrip(".")
            if key in props:
                out.extend(validate(v, props[key], sub))
            elif schema.get("additionalProperties", True) is False:
                out.append((sub, "unexpected key"))
    return out
