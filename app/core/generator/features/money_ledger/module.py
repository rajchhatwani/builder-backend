"""The money pack's `ledger` block (D1), emitted only when the spec declares `packs.money.ledger`
(validation requires auth, the `currency` block and rbac):

  app/money/ledger/config.py     roles and limits from the spec (data)
  app/money/ledger/models.py     ledger_accounts, ledger_transactions, ledger_entries
  app/money/ledger/schemas.py    request / response models (StrictInt amounts)
  app/money/ledger/service.py    post (idempotent), reverse, reads; balances are SUM(entries), never stored
  app/money/ledger/router.py     /ledger/* routes
  alembic/versions/0030_money_ledger.py   tables plus the database guards: a DEFERRABLE INITIALLY DEFERRED
                                 constraint trigger (every transaction sums to zero per currency, at least two
                                 entries, one tenant), append-only triggers (UPDATE and DELETE are refused)

The tables carry the same tenant treatment as generated CRUD tables: a `tenant_id` column (FK to auth_tenants)
on multi-tenant projects, every query confined to the caller's tenant.
"""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_packs import ledger_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/money/ledger/__init__.py.tpl",
    "app/money/ledger/schemas.py.tpl",
)


def ledger_enabled(project: ProjectCtx) -> bool:
    """Declared in the spec and the project has auth (validation refuses the declaration without it)."""
    return ledger_active(project.spec) and project.auth is not None


class MoneyLedgerModule:
    name = "money_ledger"
    manifest = ModuleManifest(
        id="money_ledger", version="1", depends_on=("crud", "auth", "money_currency"), pack="money.ledger"
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not ledger_enabled(project):
            return {}
        cfg = project.spec.packs.money.ledger  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/money/ledger/config.py"] = render_template(
            self._env,
            "app/money/ledger/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            post_roles=tuple(cfg.post_roles),
            max_amount=cfg.max_amount_minor,
            max_entries=cfg.max_entries,
            tenant=tenant,
        )
        for name in ("models", "service", "router"):
            files[f"app/money/ledger/{name}.py"] = render_template(
                self._env, f"app/money/ledger/{name}.py.j2", tenant=tenant
            )
        files["alembic/versions/0030_money_ledger.py"] = render_template(
            self._env, "alembic/versions/0030_money_ledger.py.j2", tenant=tenant
        )
        return files
