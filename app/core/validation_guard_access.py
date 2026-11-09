"""A transition guard must not be an oracle on a field the caller cannot read.

A guard is an expression over the record's own fields. Whoever may trigger a move (or see an
automatic one happen) learns whether the guard held, so a guard over a field restricted by
`authorization.field_access` read_roles is refused unless EVERY role that can perform the move can
read that field (roles held through inheritance, as in the access layers). Code: `guard_reads_hidden_field`.
"""

from collections.abc import Callable, Iterator
from typing import Any

from app.core.expr import ExprError, Schema, check_scoped
from app.core.expr.scope import is_setting_field
from app.core.spec_models import Spec, SpecEntity, SpecTransition

Add = Callable[[str, str, str], None]

PUBLIC = "(public)"
_UPDATE_OPS = ("update", "replace")
_READ_OPS = ("list", "get")


def _held(role: str, parents: dict[str, str | None]) -> set[str]:
    held: set[str] = set()
    cursor: str | None = role
    while cursor is not None and cursor not in held:
        held.add(cursor)
        cursor = parents.get(cursor)
    return held


def _fields_in(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        if node.get("k") == "field" and not is_setting_field(str(node.get("name", ""))):
            yield str(node["name"])
        for value in node.values():
            yield from _fields_in(value)
    elif isinstance(node, list):
        for item in node:
            yield from _fields_in(item)


def _performers(spec: Spec, entity: str, t: SpecTransition, parents: dict[str, str | None]) -> set[str]:
    """Principals (role names, plus PUBLIC) that can perform the move, or watch an automatic one."""
    assert spec.auth is not None
    everyone = {r.name for r in spec.auth.roles}
    if not t.auto and t.roles:
        listed = set(t.roles)
        return {r for r in everyone if _held(r, parents) & listed}
    ops = _READ_OPS if t.auto else _UPDATE_OPS
    slots = [p for p in spec.auth.permissions if p.entity == entity and p.operation in ops]
    if not slots or any(not p.roles for p in slots):
        return everyone | {PUBLIC}  # open (or not restricted): treat everybody as able
    allowed = {role for p in slots for role in p.roles}
    return {r for r in everyone if _held(r, parents) & allowed}


def check_guard_field_access(
    spec: Spec,
    entity: SpecEntity,
    t: SpecTransition,
    path: str,
    schema: Schema,
    settings: Schema | None,
    add: Add,
) -> None:
    block = spec.authorization
    if block is None or not block.field_access or t.when is None:
        return
    if spec.auth is None or not spec.auth.enabled:
        return
    rules = {
        r.field: r.read_roles
        for r in block.field_access
        if r.entity == entity.name and r.read_roles is not None
    }
    if not rules:
        return
    try:
        typed = check_scoped(t.when, schema, settings)
    except (ExprError, RecursionError):
        return  # reported by the guard check itself
    restricted = sorted({f for f in _fields_in(typed) if f in rules})
    if not restricted:
        return
    parents = {r.name: r.inherits_from for r in spec.auth.roles}
    performers = _performers(spec, entity.name, t, parents)
    for field in restricted:
        readers = set(rules[field])
        blind = sorted(
            r for r in performers if r == PUBLIC or not _held(r, parents) & readers
        )
        if blind:
            who = "an automatic move is visible to" if t.auto else "it can be triggered by"
            add(
                f"{path}.when",
                "guard_reads_hidden_field",
                f"the guard reads {entity.name}.{field}, which {', '.join(blind)[:80]} may not read "
                f"({who} them): the result would reveal the value. Let every role that can use this "
                f"transition read the field, or guard on another field",
            )
