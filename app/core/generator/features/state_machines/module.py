"""The `state_machines` feature: lifecycles for entities, enforced by the generated API.

Emitted only when the spec has at least one state machine:

  app/state_machines/definitions.py  the machines as data (states, transitions, typed guard ASTs)
  app/state_machines/expr/           the expression runtime, copied byte for byte from app/core/expr
  app/state_machines/engine.py       guards, transitions, automatic transitions, the state log
  app/state_machines/hooks.py        lifecycle hooks that set the initial state and apply automatic moves
  app/state_machines/models.py       `state_transitions`, the append-only log (who moved what, when)
  app/state_machines/router.py       GET .../transitions, POST .../transitions/{name}, GET .../state-history
  alembic/versions/0005_state_machines.py, tests/test_state_machines.py
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.expr import Schema, canonical, check, parse
from app.core.expr import __file__ as _expr_init
from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.tests.module import _skip_reason
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_behavior import expr_schema
from app.core.validation_hooks import has_guard_hooks
from app.core.validation_payments import payments_active
from app.core.validation_storage import storage_active

_TEMPLATES = Path(__file__).parent / "templates"
_EXPR_DIR = Path(_expr_init).parent
# Files of app/core/expr the generated engine needs: the runtime and the closure compiler.
_EXPR_FILES = ("errors.py", "limits.py", "parser.py", "pyeval.py", "runtime.py")

_VERBATIM = (
    "app/state_machines/__init__.py.tpl",
    "app/state_machines/engine.py.tpl",
    "app/state_machines/hooks.py.tpl",
    "app/state_machines/models.py.tpl",
)


_GUARD_IMPORT_ANCHOR = "from app.core.errors import AppError, NotFoundError\n"
_GUARD_CALL_ANCHOR = (
    '        raise AppError("transition_refused", f"the conditions for {name} are not met", 409)\n'
)


def with_guard_hooks(engine_source: str) -> str:
    """The engine with custom transition-guard hooks called after the built-in guard. Used only for
    projects that declare such hooks, so every other project keeps the engine byte for byte."""
    for anchor in (_GUARD_IMPORT_ANCHOR, _GUARD_CALL_ANCHOR):
        if engine_source.count(anchor) != 1:
            raise RuntimeError("engine template changed: update the guard hook patch")
    text = engine_source.replace(
        _GUARD_IMPORT_ANCHOR,
        _GUARD_IMPORT_ANCHOR + "from app.hooks_gen import registry as guard_hooks\n",
    )
    return text.replace(
        _GUARD_CALL_ANCHOR,
        _GUARD_CALL_ANCHOR
        + "    try:\n"
        + "        await guard_hooks.check_guards(entity, name, item, getattr(repo, \"caller\", None))\n"
        + "    except AppError:\n"
        + "        await session.rollback()  # releases the row lock; the state stays as it was\n"
        + "        raise\n",
    )


def _copy_expr(name: str) -> str:
    """An engine file with its package prefix rewritten, nothing else changed."""
    text = (_EXPR_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    return text.replace("app.core.expr", "app.state_machines.expr")


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows (auth, payments and storage come first)."""
    if project.auth is None:
        return "0001"
    if storage_active(project.spec):
        return "0004"
    if payments_active(project.spec):
        return "0003"
    return "0002"


def machine_data(project: ProjectCtx) -> dict[str, Any]:
    """Every machine as plain data: guards are type-checked ASTs, never source text to run."""
    out: dict[str, Any] = {}
    by_entity = {e.name: e for e in project.spec.entities}
    ctx_by_name = project.entity_by_name
    for sm in sorted(project.spec.state_machines, key=lambda m: m.entity):
        entity = by_entity[sm.entity]
        schema: Schema = expr_schema(entity)
        field = next(f for f in entity.fields if f.name == sm.field)
        transitions = []
        for t in sm.transitions:
            guard = canonical(check(parse(t.when), schema)) if t.when is not None else None
            transitions.append(
                {
                    "name": t.name,
                    "from": sorted(set(t.from_states)),
                    "to": t.to_state,
                    "when": t.when,
                    "roles": sorted(set(t.roles)),
                    "auto": t.auto,
                    "guard": guard,
                }
            )
        out[sm.entity] = {
            "table": ctx_by_name[sm.entity].table,
            "field": sm.field,
            "initial": sm.initial,
            "states": list(field.enum_values or []),
            "transitions": transitions,
        }
    return out


class StateMachinesModule:
    name = "state_machines"
    manifest = ModuleManifest(id="state_machines", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not project.spec.state_machines:
            return {}
        machines = machine_data(project)
        entities = [project.entity_by_name[name] for name in machines]
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        if has_guard_hooks(project.spec):
            files["app/state_machines/engine.py"] = with_guard_hooks(files["app/state_machines/engine.py"])
        files["app/state_machines/expr/__init__.py"] = ""
        for name in _EXPR_FILES:
            files[f"app/state_machines/expr/{name}"] = _copy_expr(name)
        body = pprint.pformat(machines, width=96, sort_dicts=True)
        files["app/state_machines/definitions.py"] = (
            '"""State machines (generated from the spec: change them in the builder).\n\n'
            "Plain data. A guard is a type-checked expression tree run by app/state_machines/expr;\n"
            'nothing in this file is ever evaluated as code."""\n\n'
            f"MACHINES = {body}\n"
        )
        # An entity's own access rule finds the record; the first operation it has is used.
        routes = []
        for e in entities:
            op = next((o for o in ("get", "update", "list") if o in e.access_ops), None)
            # Policy (abac / pbac) entities: a move is a change, so the caller must also pass the
            # entity's UPDATE decision (a caller whose PATCH is denied cannot move or reopen a record).
            # Role-permission entities keep the read access: a transition's own `roles` decide.
            post_op = "update" if e.policy and "update" in e.access_ops else op
            gated = any(t["roles"] for t in machines[e.name]["transitions"])
            routes.append(
                {
                    "e": e,
                    "access_op": op,
                    "post_op": post_op,
                    "gated": gated,
                    "skip": _skip_reason(e, project),
                }
            )
        context = {"routes": routes, "auth": project.auth is not None}
        files["app/state_machines/router.py"] = render_template(
            self._env, "app/state_machines/router.py.j2", **context
        )
        files["alembic/versions/0005_state_machines.py"] = render_template(
            self._env,
            "alembic/versions/0005_state_machines.py.j2",
            down_revision=migration_parent(project),
        )
        files["tests/test_state_machines.py"] = render_template(
            self._env,
            "tests/test_state_machines.py.j2",
            routes=routes,
            machines=machines,
            auth=project.auth is not None,
        )
        return files
