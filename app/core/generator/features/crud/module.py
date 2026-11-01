"""The `crud` feature: models, schemas, repositories, routers, app wiring, Alembic."""

from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.change_history.module import router_present as history_router_present
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_documents import documents_active
from app.core.validation_observability import observability_active
from app.core.validation_history import history_active
from app.core.validation_payments import payments_active
from app.core.validation_runtime import runtime_config_active, runtime_router_present
from app.core.validation_seed import seed_active
from app.core.validation_storage import storage_active

_TEMPLATES = Path(__file__).parent / "templates"

# Rendered once per project: template -> output path comes from stripping the suffix.
_VERBATIM = (
    "app/__init__.py.tpl",
    "app/config.py.tpl",
    "app/db.py.tpl",
    "app/core/__init__.py.tpl",
    "app/core/errors.py.tpl",
    "app/core/logging.py.tpl",
    "app/core/pagination.py.tpl",
    "app/core/redact.py.tpl",
    "app/crud/__init__.py.tpl",
    "app/crud/_base.py.tpl",
    "app/crud/lifecycle.py.tpl",
    "app/custom_routers/__init__.py.tpl",
    "app/hooks/__init__.py.tpl",
    "app/models/_base.py.tpl",
    "app/routers/__init__.py.tpl",
    "app/routers/_health.py.tpl",
    "app/schemas/__init__.py.tpl",
    "alembic.ini.tpl",
    "alembic/env.py.tpl",
    "alembic/script.py.mako.tpl",
)

# Rendered once per entity: (template, output path pattern)
_PER_ENTITY = (
    ("app/models/entity.py.j2", "app/models/{table}.py"),
    ("app/schemas/entity.py.j2", "app/schemas/{table}.py"),
    ("app/crud/entity.py.j2", "app/crud/{table}.py"),
    ("app/routers/entity.py.j2", "app/routers/{table}.py"),
)


class CrudModule:
    name = "crud"
    manifest = ModuleManifest(id="crud", version="1", depends_on=())

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        common: dict[str, Any] = {
            "name": project.name,
            "entities": project.entities,
            "joins": project.join_tables,
            "auth": project.auth,
            "payments": payments_active(project.spec) and project.auth is not None,
            "storage": storage_active(project.spec) and project.auth is not None,
            "observability": observability_active(project.spec) is not None,
            "documents": documents_active(project.spec) is not None and project.auth is not None,
            "state_machines": bool(project.spec.state_machines),
            "runtime_config": runtime_config_active(project.spec),
            "runtime_router": runtime_router_present(project.spec),
            "change_history": history_active(project.spec),
            "history_router": history_router_present(project),
            "seed": seed_active(project.spec),
        }
        files["app/main.py"] = render_template(self._env, "app/main.py.j2", **common)
        files["app/models/__init__.py"] = render_template(
            self._env, "app/models/__init__.py.j2", **common
        )
        files["app/models/_associations.py"] = render_template(
            self._env, "app/models/_associations.py.j2", **common
        )
        for entity in project.entities:
            for template, pattern in _PER_ENTITY:
                files[pattern.format(table=entity.table)] = render_template(
                    self._env, template, e=entity
                )
        has_jsonb = any(f.type == "json" for e in project.entities for f in e.fields)
        files["alembic/versions/0001_initial.py"] = render_template(
            self._env, "alembic/versions/0001_initial.py.j2", has_jsonb=has_jsonb, **common
        )
        return files
