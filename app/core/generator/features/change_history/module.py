"""The `change_history` feature: opt-in, per-field change history with actor and retention.

Emitted only when the spec has at least one `history` config:

  app/change_history/definitions.py  which fields of which entities are recorded, retention, view roles
  app/change_history/models.py       `ch_changes`: one row per audited field change
  app/change_history/hooks.py        lifecycle hooks (snapshot in before_save, rows in after_save), value cap, hook merge
  app/change_history/router.py       GET /<entity>/{id}/history for the entity's view roles (needs auth)
  app/change_history/purge.py        `python -m app.change_history.purge` removes rows older than retention
  alembic/versions/0007_change_history.py, tests/test_change_history.py
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.runtime_config.module import migration_parent as _before_runtime
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_history import MAX_VALUE_BYTES, history_active
from app.core.validation_runtime import runtime_config_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/change_history/__init__.py.tpl",
    "app/change_history/models.py.tpl",
    "app/change_history/hooks.py.tpl",
    "app/change_history/purge.py.tpl",
)


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows: runtime config's (0006) when the project has it,
    else the state machines' (0005) when it has those, else whatever precedes them."""
    if runtime_config_active(project.spec):
        return "0006"
    return _before_runtime(project)


def router_present(project: ProjectCtx) -> bool:
    """Reading history is role-gated, so it needs auth and at least one entity with view roles."""
    return project.auth is not None and any(h.view_roles for h in project.spec.history)


def definitions(project: ProjectCtx) -> dict[str, Any]:
    return {
        h.entity: {
            "table": project.entity_by_name[h.entity].table,
            "path": project.entity_by_name[h.entity].path,
            "fields": sorted(set(h.fields)),
            "retention_days": h.retention_days,
            "view_roles": sorted(set(h.view_roles)),
        }
        for h in sorted(project.spec.history, key=lambda x: x.entity)
    }


class ChangeHistoryModule:
    name = "change_history"
    manifest = ModuleManifest(id="change_history", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not history_active(project.spec):
            return {}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        data = definitions(project)
        body = pprint.pformat(data, width=96, sort_dicts=True)
        files["app/change_history/definitions.py"] = (
            '"""Change history (generated from the spec: change it in the builder).\n\n'
            'Plain data. Only the fields listed here are ever recorded."""\n\n'
            f"MAX_VALUE_BYTES = {MAX_VALUE_BYTES}\n\n"
            f"HISTORY = {body}\n"
        )
        if router_present(project):
            routes = []
            for name, d in data.items():
                if not d["view_roles"]:
                    continue
                e = project.entity_by_name[name]
                op = next((o for o in ("get", "update", "list") if o in e.access_ops), None)
                routes.append({"e": e, "access_op": op})
            files["app/change_history/router.py"] = render_template(
                self._env, "app/change_history/router.py.j2", routes=routes
            )
        files["alembic/versions/0007_change_history.py"] = render_template(
            self._env,
            "alembic/versions/0007_change_history.py.j2",
            down_revision=migration_parent(project),
        )
        files["tests/test_change_history.py"] = render_template(
            self._env, "tests/test_change_history.py.j2"
        )
        return files
