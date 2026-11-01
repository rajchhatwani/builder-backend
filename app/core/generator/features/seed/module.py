"""The `seed` feature: deterministic demo and dev data for a generated project.

Emitted only when the spec has at least one seed profile:

  app/seed/engine.py       the deterministic engine, copied byte for byte from app/core/seed_engine.py
  app/seed/definitions.py  entities, columns, foreign keys and state machines as plain data
  app/seed/plan.py         the seed plan: profiles, counts, per-column generators (data only)
  app/seed/guard.py        production guard (APP_ENV / ENVIRONMENT, explicit double override)
  app/seed/runner.py       writes a profile in one transaction; reset removes exactly the seeded rows
  app/seed/invariants.py   checks run after every seed (foreign keys, uniques, tenants, states, history)
  app/seed/models.py       `seed_rows`: which rows the seed created
  app/seed/__main__.py     `python -m app.seed --profile demo [--reset] [--check]`
  alembic/versions/0008_seed.py, tests/test_seed.py
"""

import pprint
from pathlib import Path
from typing import Any

from app.core import seed_engine
from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.change_history.module import migration_parent as _before_history
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_history import history_active
from app.core.validation_seed import multi_tenant, seed_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/seed/__init__.py.tpl",
    "app/seed/__main__.py.tpl",
    "app/seed/guard.py.tpl",
    "app/seed/invariants.py.tpl",
    "app/seed/models.py.tpl",
    "app/seed/runner.py.tpl",
)


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows: change history's (0007) when the project has it,
    else whatever change history would have followed (0006 runtime config, 0005 state machines ...)."""
    if history_active(project.spec):
        return "0007"
    return _before_history(project)


def definitions(project: ProjectCtx) -> dict[str, Any]:
    """Everything the engine and the checker need to know about the entities, as plain data."""
    machines = {m.entity: m for m in project.spec.state_machines}
    entities: dict[str, Any] = {}
    for e in project.entities:
        spec_entity = next(s for s in project.spec.entities if s.name == e.name)
        machine = machines.get(e.name)
        states = [f.enum_values for f in spec_entity.fields if machine and f.name == machine.field]
        entities[e.name] = {
            "table": e.table,
            "tenant_scoped": e.tenant_scoped,
            "soft_delete": e.soft_delete,
            "fields": {
                f.name: {
                    "type": f.type,
                    "required": f.required,
                    "unique": f.unique,
                    "max_length": f.max_length,
                    "min_value": f.min_value,
                    "max_value": f.max_value,
                    "enum_values": list(f.enum_values) if f.enum_values else None,
                }
                for f in spec_entity.fields
            },
            "fks": {
                fk.column: {
                    "target": fk.target_entity,
                    "table": fk.target_table,
                    "required": fk.required,
                    "unique": fk.unique,
                }
                for fk in e.fks
            },
            "machine": None
            if machine is None
            else {
                "field": machine.field,
                "initial": machine.initial,
                "states": list(states[0] or []) if states else [],
                "transitions": [
                    {
                        "name": t.name,
                        "from": sorted(set(t.from_states)),
                        "to": t.to_state,
                        "auto": t.auto,
                    }
                    for t in sorted(machine.transitions, key=lambda t: t.name)
                ],
            },
        }
    return {
        "tenant_table": "auth_tenants" if multi_tenant(project.spec) else None,
        "entities": entities,
    }


def plan_data(project: ProjectCtx) -> dict[str, Any]:
    return {
        p.name: p.model_dump(mode="json", exclude_none=True)
        for p in sorted(project.spec.seed, key=lambda x: x.name)
    }


class SeedModule:
    name = "seed"
    manifest = ModuleManifest(id="seed", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not seed_active(project.spec):
            return {}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        files["app/seed/engine.py"] = (
            Path(seed_engine.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
        )
        files["app/seed/definitions.py"] = (
            '"""What the seed engine knows about the entities (generated from the spec: change it in the builder).\n\n'
            'Plain data."""\n\n'
            f"DEFINITIONS = {pprint.pformat(definitions(project), width=96, sort_dicts=True)}\n"
        )
        files["app/seed/plan.py"] = (
            '"""The seed plan: which rows each profile creates. Data only; nothing here is ever run as code.\n\n'
            "Edit it in the builder (the same profile always yields the same rows: `seed` is the only source\n"
            'of randomness and `as_of` the only clock)."""\n\n'
            f"PROFILES = {pprint.pformat(plan_data(project), width=96, sort_dicts=True)}\n"
        )
        files["alembic/versions/0008_seed.py"] = render_template(
            self._env, "alembic/versions/0008_seed.py.j2", down_revision=migration_parent(project)
        )
        files["tests/test_seed.py"] = render_template(self._env, "tests/test_seed.py.j2")
        return files
