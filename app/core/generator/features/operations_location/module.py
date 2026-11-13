"""The operations pack's `location` block (D14), emitted only when the spec declares `packs.operations.location`:

  app/operations/location/config.py   roles, history cap, limits (data from the spec)
  app/operations/location/models.py   location_positions (latest per subject), location_history (bounded)
  app/operations/location/schemas.py  request / response models
  app/operations/location/service.py  monotonic-seq upsert, history trimming, latest-in-box, geofence events (with geo)
  app/operations/location/router.py   /location/* routes
  alembic/versions/0034_operations_location.py

Same tenant treatment as the ledger: a `tenant_id` FK to auth_tenants on multi-tenant projects."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.operations_common.module import operations_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_operations import geo_active, location_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = tuple(f"app/operations/location/{name}.py.tpl" for name in ("__init__", "schemas", "router"))


def location_enabled(project: ProjectCtx) -> bool:
    return operations_enabled(project) and location_active(project.spec)


class OperationsLocationModule:
    name = "operations_location"
    manifest = ModuleManifest(
        id="operations_location",
        version="1",
        depends_on=("crud", "auth", "operations_common", "operations_geo"),
        pack="operations.location",
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not location_enabled(project):
            return {}
        cfg = project.spec.packs.operations.location  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        geo = geo_active(project.spec)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/operations/location/config.py"] = render_template(
            self._env,
            "app/operations/location/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            write_roles=tuple(cfg.write_roles),
            history_cap=cfg.history_cap,
            max_subjects=cfg.max_subjects,
            geo=geo,
            tenant=tenant,
        )
        for name in ("models", "service"):
            files[f"app/operations/location/{name}.py"] = render_template(
                self._env, f"app/operations/location/{name}.py.j2", tenant=tenant, geo=geo
            )
        files["alembic/versions/0034_operations_location.py"] = render_template(
            self._env, "alembic/versions/0034_operations_location.py.j2", tenant=tenant
        )
        return files
