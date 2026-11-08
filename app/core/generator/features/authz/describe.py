"""Policy conditions in plain English, for the generated documentation (and reviewers).

Pure text from validated data: nothing here is evaluated, and every literal goes through `repr`
or JSON encoding so a policy value can never turn into markup.
"""

import json
from typing import Any

_OPS = {
    "eq": "is",
    "ne": "is not",
    "lt": "is less than",
    "lte": "is at most",
    "gt": "is more than",
    "gte": "is at least",
    "in": "is one of",
    "not_in": "is not one of",
    "is_null": "is empty",
    "not_null": "is set",
    "ip_in": "is inside the network",
}
_ENV = {
    "hour_utc": "the current hour (UTC)",
    "weekday_utc": "the weekday (UTC, Monday is 0)",
    "client_ip": "your IP address",
}


def _operand(operand: dict[str, Any]) -> str:
    ((kind, name),) = operand.items()
    if kind == "subject":
        return "your roles" if name == "roles" else f"your {name.replace('_', ' ')}"
    if kind == "resource":
        return f"the record's {name.replace('_', ' ')}"
    if kind == "env":
        return str(_ENV.get(name, name))
    return json.dumps(name, ensure_ascii=True)


def describe(node: dict[str, Any] | None) -> str:
    if node is None:
        return "always"
    for key, joiner in (("all", " and "), ("any", " or ")):
        if key in node:
            parts = [describe(child) for child in node[key]]
            return parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"
    left = _operand(node["left"])
    word = _OPS[node["op"]]
    if "right" not in node:
        return f"{left} {word}"
    return f"{left} {word} {_operand(node['right'])}"
