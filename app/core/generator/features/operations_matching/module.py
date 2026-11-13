"""The operations pack's `matching` block (D15), emitted only when the spec declares `packs.operations.matching`:

  app/operations/matching/config.py    roles, weights, rules, offer lifetime (data from the spec)
  app/operations/matching/scoring.py   pure: integer score, the score hook (`adjust_score`), rank, batch solver
  app/operations/matching/models.py    match_assignments (partial UNIQUE: one active assignment per request)
  app/operations/matching/schemas.py   request / response models
  app/operations/matching/service.py   rank, assign, batch (optional commit), accept / reject / expire
  app/operations/matching/router.py    /matching/* routes
  alembic/versions/0035_operations_matching.py

Same tenant treatment as the ledger: a `tenant_id` FK to auth_tenants on multi-tenant projects."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.operations_common.module import operations_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_operations import location_active, matching_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = tuple(f"app/operations/matching/{name}.py.tpl" for name in ("__init__", "scoring", "schemas", "router"))


def matching_enabled(project: ProjectCtx) -> bool:
    return operations_enabled(project) and matching_active(project.spec)


class OperationsMatchingModule:
    name = "operations_matching"
    manifest = ModuleManifest(
        id="operations_matching",
        version="1",
        depends_on=("crud", "auth", "operations_common", "operations_location"),
        pack="operations.matching",
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not matching_enabled(project):
            return {}
        cfg = project.spec.packs.operations.matching  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        location = location_active(project.spec)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/operations/matching/config.py"] = render_template(
            self._env,
            "app/operations/matching/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            assign_roles=tuple(cfg.assign_roles),
            w_distance=cfg.weights.distance,
            w_load=cfg.weights.load,
            w_rating=cfg.weights.rating,
            max_distance=cfg.max_distance_m,
            max_load=cfg.max_load,
            ttl=cfg.offer_ttl_seconds,
            location=location,
            tenant=tenant,
        )
        files["app/operations/matching/models.py"] = render_template(
            self._env, "app/operations/matching/models.py.j2", tenant=tenant
        )
        files["app/operations/matching/service.py"] = render_template(
            self._env, "app/operations/matching/service.py.j2", tenant=tenant, location=location
        )
        files["alembic/versions/0035_operations_matching.py"] = render_template(
            self._env, "alembic/versions/0035_operations_matching.py.j2", tenant=tenant
        )
        return files
