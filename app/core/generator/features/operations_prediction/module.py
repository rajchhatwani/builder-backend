"""The operations pack's `prediction` block (D16), emitted only when the spec declares `packs.operations.prediction`:

  app/operations/prediction/config.py    roles, model id, unit, fake interval width (data from the spec)
  app/operations/prediction/adapter.py   the Predictor interface and the deterministic FAKE model
  app/operations/prediction/models.py    prediction_records (value, low, high, actual)
  app/operations/prediction/schemas.py   request / response models
  app/operations/prediction/service.py   predict, record actual (once), list, logged-vs-actual stats
  app/operations/prediction/router.py    /prediction/* routes
  alembic/versions/0036_operations_prediction.py

Same tenant treatment as the ledger: a `tenant_id` FK to auth_tenants on multi-tenant projects."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.operations_common.module import operations_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_operations import prediction_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = tuple(
    f"app/operations/prediction/{name}.py.tpl" for name in ("__init__", "adapter", "schemas", "service", "router")
)


def prediction_enabled(project: ProjectCtx) -> bool:
    return operations_enabled(project) and prediction_active(project.spec)


class OperationsPredictionModule:
    name = "operations_prediction"
    manifest = ModuleManifest(
        id="operations_prediction", version="1", depends_on=("crud", "auth", "operations_common"), pack="operations.prediction"
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not prediction_enabled(project):
            return {}
        cfg = project.spec.packs.operations.prediction  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/operations/prediction/config.py"] = render_template(
            self._env,
            "app/operations/prediction/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            write_roles=tuple(cfg.write_roles),
            model_id=cfg.model_id,
            unit=cfg.unit,
            interval_bp=cfg.interval_bp,
            tenant=tenant,
        )
        files["app/operations/prediction/models.py"] = render_template(
            self._env, "app/operations/prediction/models.py.j2", tenant=tenant
        )
        files["alembic/versions/0036_operations_prediction.py"] = render_template(
            self._env, "alembic/versions/0036_operations_prediction.py.j2", tenant=tenant
        )
        return files
