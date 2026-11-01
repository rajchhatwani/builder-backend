"""The `runtime_config` feature: settings, gapless sequences and tenant-editable lists.

Emitted only when the spec has at least one setting, sequence or list:

  app/runtime_config/definitions.py  the definitions as plain data (nothing in it is ever evaluated)
  app/runtime_config/models.py       rc_settings, rc_sequences, rc_list_items
  app/runtime_config/settings.py     typed, range-checked settings with defaults
  app/runtime_config/sequences.py    `next_number`: row-locked counter taken inside the caller's transaction
  app/runtime_config/lists.py        system default values plus the tenant's own entries
  app/runtime_config/router.py       /config/settings, /config/lists, /config/sequences with role checks
  alembic/versions/0006_runtime_config.py, tests/test_runtime_config.py
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.state_machines.module import migration_parent as _before_machines
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_runtime import (
    DEFAULT_MAX_LENGTH,
    runtime_config_active,
    runtime_router_present,
)

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/runtime_config/__init__.py.tpl",
    "app/runtime_config/models.py.tpl",
    "app/runtime_config/settings.py.tpl",
    "app/runtime_config/sequences.py.tpl",
    "app/runtime_config/lists.py.tpl",
)


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows: the state machines' (0005) when the project has
    them, else whatever precedes those (auth 0002, payments 0003, storage 0004, or the initial 0001)."""
    if project.spec.state_machines:
        return "0005"
    return _before_machines(project)


def definitions(project: ProjectCtx) -> dict[str, Any]:
    spec = project.spec
    settings = {
        s.key: {
            "type": s.type,
            "default": s.default,
            "label": s.label,
            "description": s.description,
            "minimum": s.minimum,
            "maximum": s.maximum,
            "max_length": (s.max_length or DEFAULT_MAX_LENGTH) if s.type == "string" else None,
            "read_roles": sorted(set(s.read_roles)),
            "edit_roles": sorted(set(s.edit_roles)),
        }
        for s in sorted(spec.settings, key=lambda x: x.key)
    }
    sequences = {
        q.name: {
            "prefix": q.prefix,
            "padding": q.padding,
            "start": q.start,
            "per_tenant": q.per_tenant,
            "reset_yearly": q.reset_yearly,
            "view_roles": sorted(set(q.view_roles)),
        }
        for q in sorted(spec.sequences, key=lambda x: x.name)
    }
    lists = {
        lst.name: {
            "label": lst.label,
            "max_items": lst.max_items,
            "edit_roles": sorted(set(lst.edit_roles)),
            "items": [
                {"value": i.value, "label": i.label, "color": i.color, "locked": i.locked}
                for i in lst.items
            ],
        }
        for lst in sorted(spec.lists, key=lambda x: x.name)
    }
    return {"SETTINGS": settings, "SEQUENCES": sequences, "LISTS": lists}


class RuntimeConfigModule:
    name = "runtime_config"
    manifest = ModuleManifest(id="runtime_config", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        spec = project.spec
        if not runtime_config_active(spec):
            return {}
        auth = project.auth is not None
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        data = definitions(project)
        multi_tenant = bool(spec.auth is not None and spec.auth.multi_tenant) and auth
        body = "\n\n".join(
            f"{name} = {pprint.pformat(value, width=96, sort_dicts=True)}"
            for name, value in data.items()
        )
        files["app/runtime_config/definitions.py"] = (
            '"""Runtime configuration (generated from the spec: change it in the builder).\n\n'
            'Plain data; nothing in this file is ever evaluated as code."""\n\n'
            f"{body}\n"
        )
        settings = bool(spec.settings)
        lists = bool(spec.lists)
        sequences = bool(spec.sequences)
        if runtime_router_present(spec):
            names = (
                (["LISTS"] if lists else [])
                + (["SEQUENCES"] if auth and sequences else [])
                + (["SETTINGS"] if settings else [])
            )
            files["app/runtime_config/router.py"] = render_template(
                self._env,
                "app/runtime_config/router.py.j2",
                auth=auth,
                settings=settings,
                lists=lists,
                sequences=sequences,
                multi_tenant=multi_tenant,
                defs=", ".join(names),
            )
        files["alembic/versions/0006_runtime_config.py"] = render_template(
            self._env,
            "alembic/versions/0006_runtime_config.py.j2",
            down_revision=migration_parent(project),
        )
        files["tests/test_runtime_config.py"] = render_template(
            self._env,
            "tests/test_runtime_config.py.j2",
            settings=data["SETTINGS"],
            sequences=data["SEQUENCES"],
            lists=data["LISTS"],
            multi_tenant=multi_tenant,
        )
        return files


