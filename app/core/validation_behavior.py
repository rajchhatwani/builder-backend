"""Validation for the `state_machines` section. Issues go through `add(path, code, message)`."""

import re
from collections.abc import Callable
from typing import NamedTuple

from app.core.expr import ExprError, Schema, check_scoped, settings_used
from app.core.spec_models import Spec, SpecEntity, SpecStateMachine
from app.core.validation_seed import multi_tenant, tenant_scoped

Add = Callable[[str, str, str], None]

NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_TRANSITIONS = 100
MAX_GUARD_LENGTH = 1000
_EXPR_TYPES = {
    "string": "string",
    "text": "string",
    "enum": "string",
    "integer": "int",
    "bigint": "int",
    "decimal": "decimal",
    "boolean": "bool",
}


def expr_schema(entity: SpecEntity) -> Schema:
    """Fields a guard may read: the types the expression engine supports, nothing else."""
    return {
        f.name: (_EXPR_TYPES[f.type], not f.required)
        for f in entity.fields
        if f.type in _EXPR_TYPES
    }


def settings_schema(spec: Spec) -> Schema:
    """Settings a guard may read (`settings.<key>`): key -> (type, nullable). Every setting has a
    default (validation_runtime), so none is ever null."""
    return {
        s.key: (s.type, False)
        for s in spec.settings
        if s.type in ("string", "int", "bool", "decimal")
    }


def check_state_machines(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    seen: set[str] = set()
    role_names = {r.name for r in spec.auth.roles} if spec.auth is not None else set()
    for i, sm in enumerate(spec.state_machines):
        p = f"state_machines[{i}]"
        entity = entities.get(sm.entity)
        if entity is None:
            add(f"{p}.entity", "unknown_entity", f"no entity named {sm.entity!r}")
            continue
        if sm.entity in seen:
            add(f"{p}.entity", "duplicate", f"{sm.entity} already has a state machine")
        seen.add(sm.entity)
        _check_machine(spec, sm, entity, p, role_names, add)


def _check_machine(
    spec: Spec,
    sm: SpecStateMachine,
    entity: SpecEntity,
    p: str,
    role_names: set[str],
    add: Add,
) -> None:
    field = next((f for f in entity.fields if f.name == sm.field), None)
    if field is None or field.type != "enum":
        add(f"{p}.field", "invalid_value", f"{sm.field!r} must be an enum field of {sm.entity}")
        return
    if not field.required:
        add(
            f"{p}.field",
            "invalid_value",
            f"{sm.field} must be required: a record always has a state",
        )
    if field.default is not None and field.default != sm.initial:
        add(f"{p}.field", "invalid_value", f"{sm.field} has a default other than the initial state")
    states = set(field.enum_values or [])
    if sm.initial not in states:
        add(f"{p}.initial", "unknown_state", f"{sm.initial!r} is not in {sm.field}.enum_values")
    if len(sm.transitions) > MAX_TRANSITIONS:
        add(f"{p}.transitions", "too_many", f"at most {MAX_TRANSITIONS} transitions")
        return
    schema = expr_schema(entity)
    settings = settings_schema(spec)
    names: set[str] = set()
    auto_edges: dict[str, set[str]] = {}
    for j, t in enumerate(sm.transitions):
        tp = f"{p}.transitions[{j}]"
        if not NAME_RE.fullmatch(t.name):
            add(f"{tp}.name", "invalid_value", "use lowercase letters, digits and '_' (max 40)")
        elif t.name in names:
            add(f"{tp}.name", "duplicate_name", f"transition {t.name} is listed twice")
        names.add(t.name)
        if not t.from_states:
            add(f"{tp}.from_states", "required", "name at least one state to move from")
        for k, s in enumerate(t.from_states):
            if s not in states:
                add(f"{tp}.from_states[{k}]", "unknown_state", f"{s!r} is not a state")
        if t.to_state not in states:
            add(f"{tp}.to_state", "unknown_state", f"{t.to_state!r} is not a state")
        if t.when is not None:
            _check_guard(t.when, schema, f"{tp}.when", add, settings)
            if (
                _reads_settings(t.when, schema, settings)
                and multi_tenant(spec)
                and not tenant_scoped(spec, entity)
            ):
                add(
                    f"{tp}.when",
                    "tenancy_required",
                    f"settings are kept per tenant, but {entity.name} does not belong to a tenant: "
                    "a guard cannot know whose settings to read",
                )
        if t.auto and t.roles:
            add(f"{tp}.roles", "invalid_value", "an automatic transition has no roles")
        if t.roles:
            if spec.auth is None or not spec.auth.enabled:
                add(f"{tp}.roles", "auth_required", "roles need the auth feature switched on")
            for k, role in enumerate(t.roles):
                if spec.auth is not None and spec.auth.enabled and role not in role_names:
                    add(f"{tp}.roles[{k}]", "unknown_role", f"no role named {role!r}")
        if t.auto:
            for s in t.from_states:
                auto_edges.setdefault(s, set()).add(t.to_state)
    if _has_cycle(auto_edges):
        add(f"{p}.transitions", "auto_cycle", "automatic transitions must not form a loop")


class ExprVerdict(NamedTuple):
    """Outcome of checking one expression. `code`/`message` are exactly what validation reports."""

    ok: bool
    type: str | None
    code: str | None
    message: str | None
    pos: int


def check_expression(
    source: str, schema: Schema, expect: str = "bool", settings: Schema | None = None
) -> ExprVerdict:
    """The single place that judges a guard expression: validation and the live checker share it.
    `expect` is "bool" (a guard) or "any". `settings` are the project's declared settings a guard may
    read as `settings.<key>` (None = not allowed here). Never raises for any input."""
    if len(source) > MAX_GUARD_LENGTH:
        return ExprVerdict(False, None, "too_long", f"at most {MAX_GUARD_LENGTH} characters", 0)
    try:
        typed = check_scoped(source, schema, settings)
    except ExprError as exc:
        return ExprVerdict(False, None, "invalid_expression", str(exc), exc.pos)
    except RecursionError:
        return ExprVerdict(False, None, "invalid_expression", "expression is nested too deeply", 0)
    if expect == "bool" and typed["t"] != "bool":
        msg = f"a guard must give true or false, not {typed['t']}"
        return ExprVerdict(False, typed["t"], "invalid_expression", msg, 0)
    return ExprVerdict(True, typed["t"], None, None, 0)


def _check_guard(
    source: str, schema: Schema, path: str, add: Add, settings: Schema | None = None
) -> None:
    verdict = check_expression(source, schema, settings=settings)
    if not verdict.ok:
        add(path, verdict.code or "invalid_expression", verdict.message or "")


def _reads_settings(source: str, schema: Schema, settings: Schema) -> bool:
    try:
        return bool(settings_used(check_scoped(source, schema, settings)))
    except (ExprError, RecursionError):
        return False  # already reported by _check_guard


def _has_cycle(edges: dict[str, set[str]]) -> bool:
    state: dict[str, int] = {}  # 1 = on the current path, 2 = done

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        if any(visit(n) for n in edges.get(node, ())):
            return True
        state[node] = 2
        return False

    return any(visit(n) for n in list(edges))
