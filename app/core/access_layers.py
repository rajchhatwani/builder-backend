"""Access layers (C7): object / field / row, as one matrix per spec, and the diff between two specs.

Pure functions over `Spec`; no database. The matrix answers "what can role R do to entity E"
in three layers:

    object  may R run operation `op` on E at all        (yes | conditional | no)
    field   may R read / write field F of E             (yes | no)
    row     which rows does R reach when `op` is allowed (all | own | own (admins: all) | tenant |
            filter: f=v | policy)

`access_diff(before, after)` lists every cell that changed and which roles gain or lose access.
Gaining access (or reaching more rows) is a *weakening* of the access rules: `weakens` is true, and
the typed-operations API refuses such an edit unless the caller confirms it. Entities and roles
that are new or gone are listed ("added" / "removed") but never counted as a weakening: a new
entity starts with whatever its own permissions say, reviewed when they are written.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from app.core import authz_engine as eng
from app.core.authz_tools import policy_set_from_spec
from app.core.enums import AuthorizationModel, RowRule
from app.core.spec_models import Spec
from app.core.validation import ADMIN_ROLE

PUBLIC = "(public)"  # someone who is not signed in
READ_OPS = ("list", "get")
WRITE_OPS = ("create", "replace", "update")
_NO_ACCESS_RANK = {"no": 0, "conditional": 1, "yes": 2}
# Lower = broader. Moving a cell to a lower number lets the role reach more rows.
_ROW_RANK = {"all": 0, "policy": 1, "filter": 2, "tenant": 2, "own (admins: all)": 3, "own": 4}


def _held(role: str, parents: Mapping[str, str | None]) -> set[str]:
    held: set[str] = set()
    cursor: str | None = role
    while cursor is not None and cursor not in held:
        held.add(cursor)
        cursor = parents.get(cursor)
    return held


def _row_label(rule: str | None, field: str | None, value: str | None) -> str:
    if rule is None:
        return "all"
    if rule == RowRule.owner:
        return "own"
    if rule == RowRule.role_scoped:
        return "own (admins: all)"
    if rule == RowRule.tenant:
        return "tenant"
    if rule == RowRule.custom_filter:
        return f"filter: {field}={value}"
    return str(rule)


def _row_rank(label: str) -> int:
    return _ROW_RANK.get(label.split(":", 1)[0], _ROW_RANK.get(label, 2))


class AccessMatrix:
    """Cells keyed (layer, entity, target, role) -> value."""

    def __init__(self, spec: Spec) -> None:
        self.cells: dict[tuple[str, str, str, str], str] = {}
        auth = spec.auth
        self.roles: list[str] = [r.name for r in auth.roles] if auth is not None else []
        self.entities: list[str] = [e.name for e in spec.entities]
        self._parents = {r.name: r.inherits_from for r in auth.roles} if auth is not None else {}
        self._spec = spec
        policy_model = (
            spec.authorization is not None
            and spec.authorization.model in (AuthorizationModel.abac, AuthorizationModel.pbac)
        )
        self._pset: eng.PolicySet | None = None
        self._broken = False  # policies that do not load grant nothing (fail closed)
        if policy_model:
            try:
                self._pset = policy_set_from_spec(spec)
            except eng.PolicyError:
                self._broken = True
        self._fill()

    # -- layers ------------------------------------------------------------------------------

    def _object(self, entity: str, op: str, held: set[str]) -> tuple[str, str]:
        """(access, row label) of someone holding `held` for one operation."""
        if self._broken:
            return "no", "all"
        if self._pset is not None:
            rules = eng.applicable(self._pset, sorted(held), entity, op)
            allows = [p for _, p in rules if p["effect"] == "allow"]
            denies = [p for _, p in rules if p["effect"] == "deny"]
            if not allows or any(p["when"] is None for p in denies):
                return "no", "all"
            if any(p["when"] is None for p in allows) and not denies:
                return "yes", "all"
            return "conditional", "policy"
        auth = self._spec.auth
        if auth is None or not auth.enabled:
            return "yes", "all"  # no sign-in: every route is public
        perm = None
        if auth is not None:
            perm = next(
                (p for p in auth.permissions if p.entity == entity and p.operation == op), None
            )
        if perm is None or not perm.roles:
            return "yes", "all"  # no slot or an empty role list = public
        if held & set(perm.roles):
            label = _row_label(perm.row_rule, perm.custom_filter_field, perm.custom_filter_value)
            return "yes", "all" if label == "own (admins: all)" and ADMIN_ROLE in held else label
        return "no", "all"

    def _fill(self) -> None:
        spec = self._spec
        principals: list[tuple[str, set[str]]] = [(PUBLIC, set())]
        principals += [(r, _held(r, self._parents)) for r in self.roles]
        field_rules = {
            (f.entity, f.field): f
            for f in (spec.authorization.field_access if spec.authorization else [])
        }
        for entity in spec.entities:
            ops = [o for o in entity.options.operations]
            for role, held in principals:
                allowed: dict[str, str] = {}
                for op in ops:
                    access, row = self._object(entity.name, op, held)
                    allowed[op] = access
                    self.cells[("object", entity.name, op, role)] = access
                    if access != "no":
                        self.cells[("row", entity.name, op, role)] = row
                can_read = any(allowed.get(o, "no") != "no" for o in READ_OPS)
                can_write = any(allowed.get(o, "no") != "no" for o in WRITE_OPS)
                for f in entity.fields:
                    rule = field_rules.get((entity.name, f.name))
                    read = can_read and (
                        rule is None or rule.read_roles is None or bool(held & set(rule.read_roles))
                    )
                    write = can_write and (
                        rule is None
                        or rule.write_roles is None
                        or bool(held & set(rule.write_roles))
                    )
                    self.cells[("field", entity.name, f"{f.name}.read", role)] = (
                        "yes" if read else "no"
                    )
                    self.cells[("field", entity.name, f"{f.name}.write", role)] = (
                        "yes" if write else "no"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles": [*self.roles, PUBLIC],
            "entities": self.entities,
            "cells": [
                {"layer": k[0], "entity": k[1], "target": k[2], "role": k[3], "value": v}
                for k, v in sorted(self.cells.items())
            ],
        }


def access_matrix(spec: Spec) -> dict[str, Any]:
    return AccessMatrix(spec).to_dict()


def readable_fields(spec: Spec, entity: str, roles: Iterable[str]) -> set[str]:
    """Fields of `entity` that someone holding `roles` may read (object read access included)."""
    matrix = AccessMatrix(spec)
    parents = matrix._parents
    held: set[str] = set()
    for r in roles:
        if isinstance(r, str):
            held |= _held(r, parents)
    names = [e for e in spec.entities if e.name == entity]
    if not names:
        return set()
    if all(matrix._object(entity, op, held)[0] == "no" for op in READ_OPS):
        return set()
    rules = {
        f.field: f
        for f in (spec.authorization.field_access if spec.authorization else [])
        if f.entity == entity
    }
    out: set[str] = set()
    for f in names[0].fields:
        rule = rules.get(f.name)
        if rule is None or rule.read_roles is None or held & set(rule.read_roles):
            out.add(f.name)
    return out


def _effect(layer: str, before: str | None, after: str | None) -> str:
    if before is None:
        return "added"
    if after is None:
        return "removed"
    if layer == "row":
        a, b = _row_rank(before), _row_rank(after)
        return "gain" if b < a else "lose" if b > a else "change"
    a, b = _NO_ACCESS_RANK.get(before, 0), _NO_ACCESS_RANK.get(after, 0)
    return "gain" if b > a else "lose" if b < a else "change"


def access_diff(before: Spec, after: Spec) -> dict[str, Any]:
    """Every access cell that differs between two specs, and which roles gain or lose."""
    m1, m2 = AccessMatrix(before), AccessMatrix(after)
    changes: list[dict[str, Any]] = []
    for key in sorted(set(m1.cells) | set(m2.cells)):
        b, a = m1.cells.get(key), m2.cells.get(key)
        if b == a:
            continue
        layer, entity, target, role = key
        # A cell whose entity or role did not exist on one side is an addition or removal of that
        # entity/role, not a change of an existing rule.
        entity_new = b is None and entity not in m1.entities
        entity_gone = a is None and entity not in m2.entities
        role_new = b is None and role != PUBLIC and role not in m1.roles
        role_gone = a is None and role != PUBLIC and role not in m2.roles
        if layer == "row" and (b is None or a is None) and not (entity_new or entity_gone or role_new or role_gone):
            # a row cell appears/disappears with object access: the object cell tells the story
            continue
        effect = _effect(layer, b, a)
        if entity_new or role_new:
            effect = "added"
        elif entity_gone or role_gone:
            effect = "removed"
        changes.append(
            {
                "layer": layer,
                "entity": entity,
                "target": target,
                "role": role,
                "before": b,
                "after": a,
                "effect": effect,
            }
        )
    gaining: dict[str, list[str]] = {}
    losing: dict[str, list[str]] = {}
    for c in changes:
        label = f"{c['layer']}:{c['entity']}.{c['target']}"
        if c["effect"] == "gain":
            gaining.setdefault(c["role"], []).append(label)
        elif c["effect"] == "lose":
            losing.setdefault(c["role"], []).append(label)
    return {
        "changes": changes,
        "roles_gaining": gaining,
        "roles_losing": losing,
        "weakens": bool(gaining),
        "counts": {
            e: sum(1 for c in changes if c["effect"] == e)
            for e in ("gain", "lose", "change", "added", "removed")
        },
    }


def weakens(before: Spec, after: Spec) -> list[dict[str, Any]]:
    """The cells where `after` gives a role more access than `before` (empty = not weakened)."""
    return [c for c in access_diff(before, after)["changes"] if c["effect"] == "gain"]
