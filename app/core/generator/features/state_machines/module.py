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

from app.core.expr import Schema, canonical, check_scoped, settings_used
from app.core.expr import __file__ as _expr_init
from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.tests.module import _skip_reason
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_behavior import expr_schema, settings_schema
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


def _role_probe(
    e: Any, machine: dict[str, Any], project: Any, access_op: str | None
) -> dict[str, Any] | None:
    """What the generated tests may assert about "no roles = whoever may update": a role that can
    read the entity but not update it, plus transitions that start in the initial state with no guard.
    None when the entity's rules cannot be probed with plain role users (owner / tenant / filter rules)."""
    auth = project.auth
    if auth is None or e.owned or e.tenant_scoped or access_op is None:
        return None
    read = next((a for a in e.access if a.op == access_op), None)
    updates = [a for a in e.access if a.op in ("update", "replace")]
    if read is None or any(a.owner or a.tenant or a.match for a in [read, *updates]):
        return None
    parent = {r.name: r.inherits_from for r in auth.roles}

    def effective(names: set[str]) -> set[str]:
        out: set[str] = set()
        pending = list(names)
        while pending:
            role = pending.pop()
            if role not in out:
                out.add(role)
                if parent.get(role):
                    pending.append(parent[role])
        return out

    defaults = {r.name for r in auth.roles if r.is_default}
    can_update = [set(a.roles) for a in updates]
    if any(not roles for roles in can_update):
        return None  # any signed-in user may update: there is no reader to refuse
    readers = sorted(read.roles) if read.roles else sorted(parent)
    safe = [
        r
        for r in readers
        if all(not effective({r} | defaults) & roles for roles in can_update)
        and (not read.roles or effective({r} | defaults) & set(read.roles))
    ]
    # A guard hook (transition_guard) can refuse any move; the tests cannot know, so they try none.
    start = [
        t
        for t in machine["transitions"]
        if not t["auto"]
        and machine["initial"] in t["from"]
        and t["guard"] is None
        and not has_guard_hooks(project.spec)
    ]
    empty = next((t["name"] for t in start if not t["roles"]), None)
    roled = next(
        (
            (t["name"], role)
            for t in start
            if t["roles"]
            for role in sorted(t["roles"])
            if role in safe
        ),
        None,
    )
    if not safe:
        return None
    refused = next((t["name"] for t in machine["transitions"] if not t["auto"] and not t["roles"]), None)
    return {"reader": safe[0], "refused": refused, "empty": empty, "roled": roled}


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
        + '        await guard_hooks.check_guards(entity, name, item, getattr(repo, "caller", None))\n'
        + "    except AppError:\n"
        + "        await session.rollback()  # releases the row lock; the state stays as it was\n"
        + "        raise\n",
    )


_SETTINGS_ANCHORS = (
    "from app.state_machines.definitions import MACHINES\n",
    "from sqlalchemy.ext.asyncio import AsyncSession\n",
    "def row_values(item: Any) -> dict[str, Any]:\n"
    "    return {c.key: getattr(item, c.key, None) for c in sa.inspect(type(item)).column_attrs}\n",
    '    guard = _GUARDS.get((entity, transition["name"]))\n    if guard is None:\n        return True\n',
    "    item = locked.scalar_one()\n    state = current_state(entity, item)\n",
)
_HOOKS_SETTLE_ANCHOR = "        engine.settle(session, entity, item)\n"
_HOOKS_IMPORT_ANCHOR = "from sqlalchemy.orm import object_session\n"

_SETTINGS_ENGINE_BLOCK = '''

# --- settings in guards (`settings.<key>`) --------------------------------------------------------
# A guard reads the settings as the pseudo-fields `_setting_<key>`. They are filled from the SAME read
# path as GET /config/settings (stored value for the record's tenant, else the default) every time
# `prime_settings` runs: before a transition is applied, before automatic moves settle, before the list
# of available transitions. The values live on the request's session, so nothing survives the request,
# and a guard whose settings were not loaded is refused (fail closed).
SETTINGS_KEY = "sm_settings"
NIL_TENANT = uuid.UUID(int=0)
USED_SETTINGS = __USED__


def _setting_fields(node: Any) -> frozenset[str]:
    if isinstance(node, dict):
        found: set[str] = set()
        if node.get("k") == "field" and str(node.get("name", "")).startswith("_setting_"):
            found.add(node["name"])
        for value in node.values():
            found |= _setting_fields(value)
        return frozenset(found)
    if isinstance(node, list):
        return frozenset().union(*[_setting_fields(v) for v in node]) if node else frozenset()
    return frozenset()


_NEEDS: dict[tuple[str, str], frozenset[str]] = {
    (entity, t["name"]): _setting_fields(t["guard"])
    for entity, machine in MACHINES.items()
    for t in machine["transitions"]
    if t["guard"] is not None
}


async def prime_settings(session: AsyncSession | None, item: Any) -> None:
    """Load the current value of every setting the guards use, for the tenant the record belongs to."""
    if session is None:
        return  # not attached to a session: guards that need settings are refused
    session.info.pop(SETTINGS_KEY, None)
    tenant = getattr(item, "tenant_id", NIL_TENANT)
    if tenant is None:
        return  # no tenant, no settings: guards that need them are refused
    stored = await runtime_settings.stored_values(session, tenant)
    session.info[SETTINGS_KEY] = {
        f"_setting_{key}": runtime_settings.typed(
            key, stored[key].value if key in stored else runtime_settings.SETTINGS[key]["default"]
        )
        for key in USED_SETTINGS
    }
'''


def with_settings(engine_source: str, used: list[str]) -> str:
    """The engine with `settings.<key>` support. Used only by projects whose guards read settings, so
    every other project keeps the engine byte for byte."""
    for anchor in _SETTINGS_ANCHORS:
        if engine_source.count(anchor) != 1:
            raise RuntimeError("engine template changed: update the settings patch")
    a_import, a_session, a_rows, a_hold, a_apply = _SETTINGS_ANCHORS
    text = engine_source.replace(
        a_import, "from app.runtime_config import settings as runtime_settings\n" + a_import
    )
    text = text.replace(a_session, a_session + "from sqlalchemy.orm import object_session\n")
    text = text.replace(
        a_rows,
        "def row_values(item: Any) -> dict[str, Any]:\n"
        "    values = {c.key: getattr(item, c.key, None) for c in sa.inspect(type(item)).column_attrs}\n"
        "    session = object_session(item)\n"
        "    if session is not None:\n"
        "        values.update(session.info.get(SETTINGS_KEY) or {})\n"
        "    return values\n",
    )
    text = text.replace(
        a_hold,
        a_hold
        + '    if not _NEEDS.get((entity, transition["name"]), frozenset()) <= values.keys():\n'
        "        return False  # the settings this guard reads were not loaded: refuse\n",
    )
    text = text.replace(
        a_apply,
        "    item = locked.scalar_one()\n    await prime_settings(session, item)\n    state = current_state(entity, item)\n",
    )
    return text.rstrip("\n") + "\n" + _SETTINGS_ENGINE_BLOCK.replace("__USED__", repr(sorted(used)))


def with_settings_hooks(hooks_source: str) -> str:
    if (
        hooks_source.count(_HOOKS_SETTLE_ANCHOR) != 1
        or hooks_source.count(_HOOKS_IMPORT_ANCHOR) != 1
    ):
        raise RuntimeError("hooks template changed: update the settings patch")
    text = hooks_source.replace(
        _HOOKS_IMPORT_ANCHOR,
        "from sqlalchemy.ext.asyncio import async_object_session\n" + _HOOKS_IMPORT_ANCHOR,
    )
    # `object_session` is the sync Session; reading settings is async I/O, so use the AsyncSession.
    return text.replace(
        _HOOKS_SETTLE_ANCHOR,
        "        await engine.prime_settings(async_object_session(item), item)\n"
        + _HOOKS_SETTLE_ANCHOR,
    )


def guard_settings(machines: dict[str, Any]) -> list[str]:
    """Every setting key read by some guard, sorted."""
    used: set[str] = set()
    for machine in machines.values():
        for t in machine["transitions"]:
            if t["guard"] is not None:
                used |= settings_used(t["guard"])
    return sorted(used)


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
        settings = settings_schema(project.spec)
        field = next(f for f in entity.fields if f.name == sm.field)
        transitions = []
        for t in sm.transitions:
            guard = (
                canonical(check_scoped(t.when, schema, settings)) if t.when is not None else None
            )
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
            files["app/state_machines/engine.py"] = with_guard_hooks(
                files["app/state_machines/engine.py"]
            )
        used_settings = guard_settings(machines)
        if used_settings:
            files["app/state_machines/engine.py"] = with_settings(
                files["app/state_machines/engine.py"], used_settings
            )
            files["app/state_machines/hooks.py"] = with_settings_hooks(
                files["app/state_machines/hooks.py"]
            )
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
            # A transition with no `roles` means "whoever may update this entity": on role-permission
            # entities the router also applies the entity's own PATCH / PUT access (roles and row
            # rules) to it. A slot with no access rule is public, so there is nothing to apply.
            update_ops = (
                [
                    {"op": a.op, "needs_user": a.needs_user}
                    for a in e.access
                    if a.op in ("update", "replace")
                ]
                if not e.policy
                else []
            )
            routes.append(
                {
                    "e": e,
                    "access_op": op,
                    "post_op": post_op,
                    "gated": gated,
                    "update_ops": update_ops,
                    "probe": _role_probe(e, machines[e.name], project, op) if update_ops else None,
                    "skip": _skip_reason(e, project),
                }
            )
        context = {
            "routes": routes,
            "auth": project.auth is not None,
            "settings_guards": bool(used_settings),
        }
        files["app/state_machines/router.py"] = render_template(
            self._env, "app/state_machines/router.py.j2", **context
        )
        files["alembic/versions/0005_state_machines.py"] = render_template(
            self._env,
            "alembic/versions/0005_state_machines.py.j2",
            down_revision=migration_parent(project),
        )
        if used_settings:
            files["tests/test_state_machine_settings.py"] = render_template(
                self._env, "tests/test_state_machine_settings.py.j2"
            )
        files["tests/test_state_machines.py"] = render_template(
            self._env,
            "tests/test_state_machines.py.j2",
            routes=routes,
            machines=machines,
            auth=project.auth is not None,
        )
        return files
