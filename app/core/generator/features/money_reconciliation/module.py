"""The money pack's `reconciliation` block (D6), emitted only when the spec declares `packs.money.reconciliation`
(validation requires the ledger, auth and rbac):

  app/money/reconciliation/config.py    roles, tolerance and limits from the spec (data)
  app/money/reconciliation/models.py    reconciliation_runs / _lines / _matches / _events
  app/money/reconciliation/matcher.py   the pure matcher (integers, deterministic, one-to-one)
  app/money/reconciliation/schemas.py   request / response models (StrictInt amounts)
  app/money/reconciliation/service.py   import (idempotent), match, un-match, close with an integer summary
  app/money/reconciliation/router.py    /reconciliation/* routes
  alembic/versions/0031_money_reconciliation.py   tables, UNIQUE(entry) / UNIQUE(line) on matches, closed-run
                                        and append-only guards

Same tenant treatment as the ledger: a `tenant_id` FK to auth_tenants on multi-tenant projects."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_packs import reconciliation_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/money/reconciliation/__init__.py.tpl",
    "app/money/reconciliation/schemas.py.tpl",
    "app/money/reconciliation/matcher.py.tpl",
)


def reconciliation_enabled(project: ProjectCtx) -> bool:
    return reconciliation_active(project.spec) and project.auth is not None


class MoneyReconciliationModule:
    name = "money_reconciliation"
    manifest = ModuleManifest(
        id="money_reconciliation",
        version="1",
        depends_on=("crud", "auth", "money_currency", "money_ledger"),
        pack="money.reconciliation",
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not reconciliation_enabled(project):
            return {}
        cfg = project.spec.packs.money.reconciliation  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/money/reconciliation/config.py"] = render_template(
            self._env,
            "app/money/reconciliation/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            run_roles=tuple(cfg.run_roles),
            tolerance=cfg.tolerance_minor,
            max_lines=cfg.max_lines,
            tenant=tenant,
        )
        for name in ("models", "service", "router"):
            files[f"app/money/reconciliation/{name}.py"] = render_template(
                self._env, f"app/money/reconciliation/{name}.py.j2", tenant=tenant
            )
        files["alembic/versions/0031_money_reconciliation.py"] = render_template(
            self._env, "alembic/versions/0031_money_reconciliation.py.j2", tenant=tenant
        )
        return files
