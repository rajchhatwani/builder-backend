"""`settings.<key>` in expressions: a read-only view of the project's runtime settings.

The expression language itself has no scopes. A reference `settings.approval_threshold` is rewritten
(same length, so error positions stay right) to the reserved pseudo-field `_setting_approval_threshold`
BEFORE parsing, and the checker gets that name in its schema with the type the spec declares. Real fields
cannot start with an underscore (names are snake_case from a letter), so a setting can never be mistaken
for, or written as, an entity field; and the language has no assignment at all.

The generated engine does not parse text: it runs typed ASTs whose pseudo-fields are filled, at the time
of the check, from the same read path the settings API uses. The SQL emitter refuses them (sql.py).

This file is NOT copied into generated projects.
"""

import re
from typing import Any

from app.core.expr.check import Schema, check
from app.core.expr.errors import ExprError
from app.core.expr.parser import Node, parse

SETTING_PREFIX = "_setting_"
SCOPE = "settings"
_IDENT_START = re.compile(r"[A-Za-z_]")
_IDENT_CHAR = re.compile(r"[A-Za-z0-9_]")
# "settings." is 9 characters and so is the prefix: the rewrite never moves a character.
assert len(SCOPE) + 1 == len(SETTING_PREFIX)


def pseudo_field(key: str) -> str:
    return SETTING_PREFIX + key


def is_setting_field(name: str) -> bool:
    return name.startswith(SETTING_PREFIX)


def setting_key(name: str) -> str:
    return name[len(SETTING_PREFIX) :]


def rewrite_settings(source: str, settings: Schema | None) -> str:
    """Replace every `settings.<key>` outside string literals by its pseudo-field.

    `settings` is the project's declared settings (key -> (type, nullable)); None means this place
    cannot use settings at all. Raises ExprError (with the position) for an unknown key."""
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch in "'\"":  # a string literal is copied untouched
            j = i + 1
            while j < n and source[j] != ch:
                j += 2 if source[j] == "\\" else 1
            out.append(source[i : j + 1])
            i = j + 1
            continue
        if _IDENT_START.match(ch) and (
            i == 0 or not (_IDENT_CHAR.match(source[i - 1]) or source[i - 1] == ".")
        ):
            k = i
            while k < n and _IDENT_CHAR.match(source[k]):
                k += 1
            word = source[i:k]
            if word.startswith(SETTING_PREFIX):
                raise ExprError(f"{SETTING_PREFIX!r} is reserved: write settings.<key>", i)
            if word == SCOPE and source[k : k + 1] == ".":
                j = k + 1
                e = j
                while e < n and _IDENT_CHAR.match(source[e]):
                    e += 1
                key = source[j:e]
                if not key or not _IDENT_START.match(key[0]):
                    raise ExprError("expected a setting name after 'settings.'", j)
                if settings is None:
                    raise ExprError("settings cannot be used in this expression", i)
                if key not in settings:
                    known = ", ".join(sorted(settings)) or "none declared"
                    raise ExprError(f"unknown setting {key!r}; known settings: {known}", i)
                out.append(pseudo_field(key))
                i = e
            else:
                out.append(word)
                i = k
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def check_scoped(source: str, schema: Schema, settings: Schema | None = None) -> Node:
    """Parse and type-check `source` against the entity's fields plus read-only settings."""
    rewritten = rewrite_settings(source, settings)
    extended: Schema = dict(schema)
    for key, entry in (settings or {}).items():
        extended[pseudo_field(key)] = entry
    return check(parse(rewritten), extended)


def settings_used(typed: Node) -> set[str]:
    """The setting keys a typed expression reads."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("k") == "field" and is_setting_field(str(node.get("name", ""))):
                found.add(setting_key(node["name"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(typed)
    return found
