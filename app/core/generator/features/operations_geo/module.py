"""The operations pack's `geo` block (D13), emitted only when the spec declares `packs.operations.geo`:

  app/operations/geo/config.py     roles, limits, grid cell size (data from the spec)
  app/operations/geo/models.py     geo_places (grid `cell` index), geo_geofences, geo_memberships, geo_events
  app/operations/geo/adapters.py   geocoder / routing / ETA interfaces and the deterministic FAKE provider
  app/operations/geo/schemas.py    request / response models
  app/operations/geo/service.py    places, nearest / within, geofences, enter / exit evaluation, adapters
  app/operations/geo/router.py     /geo/* routes
  alembic/versions/0033_operations_geo.py

Same tenant treatment as the ledger: a `tenant_id` FK to auth_tenants on multi-tenant projects."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.operations_common.module import operations_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_operations import geo_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = tuple(
    f"app/operations/geo/{name}.py.tpl" for name in ("__init__", "adapters", "schemas", "service", "router")
)


def geo_enabled(project: ProjectCtx) -> bool:
    return operations_enabled(project) and geo_active(project.spec)


class OperationsGeoModule:
    name = "operations_geo"
    manifest = ModuleManifest(
        id="operations_geo", version="1", depends_on=("crud", "auth", "operations_common"), pack="operations.geo"
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not geo_enabled(project):
            return {}
        cfg = project.spec.packs.operations.geo  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/operations/geo/config.py"] = render_template(
            self._env,
            "app/operations/geo/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            write_roles=tuple(cfg.write_roles),
            provider=cfg.provider,
            grid_cell=cfg.grid_cell_micro,
            max_places=cfg.max_places,
            max_geofences=cfg.max_geofences,
            max_vertices=cfg.max_polygon_vertices,
            max_radius=cfg.max_radius_m,
            tenant=tenant,
        )
        files["app/operations/geo/models.py"] = render_template(self._env, "app/operations/geo/models.py.j2", tenant=tenant)
        files["alembic/versions/0033_operations_geo.py"] = render_template(
            self._env, "alembic/versions/0033_operations_geo.py.j2", tenant=tenant
        )
        return files
