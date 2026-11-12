"""The money pack's `invoicing` block (D7), emitted only when the spec declares `packs.money.invoicing`
(validation requires the ledger, currency, auth and rbac):

  app/money/invoicing/config.py     roles, number prefix, terms, ledger account codes, aging buckets (data)
  app/money/invoicing/models.py     invoice_counters, invoices, invoice_lines, invoice_payments (+ money_payouts)
  app/money/invoicing/rules.py      pure rules: state machine, invoice numbers, aging buckets
  app/money/invoicing/totals.py     line and invoice totals (integers, D5 tax adapter, half_even)
  app/money/invoicing/posting.py    stages ledger transactions inside the caller's database transaction
  app/money/invoicing/schemas.py    request / response models (StrictInt amounts)
  app/money/invoicing/service.py    create / update drafts, issue (gapless numbers), pay, void, aging
  app/money/invoicing/router.py     /invoices/* routes
  with `payouts`: payouts_service.py and payouts_router.py (/payouts/*)
  alembic/versions/0032_money_invoicing.py   tables and the immutability guards

Same tenant treatment as the ledger: a `tenant_id` FK to auth_tenants on multi-tenant projects.
"""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_packs import invoicing_active, payouts_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/money/invoicing/__init__.py.tpl",
    "app/money/invoicing/schemas.py.tpl",
    "app/money/invoicing/rules.py.tpl",
    "app/money/invoicing/totals.py.tpl",
)


def invoicing_enabled(project: ProjectCtx) -> bool:
    return invoicing_active(project.spec) and project.auth is not None


def payouts_enabled(project: ProjectCtx) -> bool:
    return payouts_active(project.spec) and project.auth is not None


class MoneyInvoicingModule:
    name = "money_invoicing"
    manifest = ModuleManifest(
        id="money_invoicing",
        version="1",
        depends_on=("crud", "auth", "money_currency", "money_ledger"),
        pack="money.invoicing",
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not invoicing_enabled(project):
            return {}
        cfg = project.spec.packs.money.invoicing  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        payouts = cfg.payouts
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/money/invoicing/config.py"] = render_template(
            self._env,
            "app/money/invoicing/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            write_roles=tuple(cfg.write_roles),
            prefix=cfg.number_prefix,
            terms=cfg.payment_terms_days,
            buckets=tuple(cfg.aging_buckets_days),
            receivable=cfg.receivable_account,
            payable=cfg.payable_account,
            revenue=cfg.revenue_account,
            expense=cfg.expense_account,
            tax_account=cfg.tax_account,
            cash=cfg.cash_account,
            payouts=payouts is not None,
            commission_bp=payouts.commission_bp if payouts else 0,
            seller_payable=payouts.seller_payable_account if payouts else "",
            commission_account=payouts.commission_account if payouts else "",
            tenant=tenant,
        )
        for name in ("models", "posting", "service", "router"):
            files[f"app/money/invoicing/{name}.py"] = render_template(
                self._env, f"app/money/invoicing/{name}.py.j2", tenant=tenant, payouts=payouts is not None
            )
        if payouts is not None:
            for name in ("payouts_service", "payouts_router"):
                files[f"app/money/invoicing/{name}.py"] = render_template(
                    self._env, f"app/money/invoicing/{name}.py.j2", tenant=tenant
                )
        files["alembic/versions/0032_money_invoicing.py"] = render_template(
            self._env, "alembic/versions/0032_money_invoicing.py.j2", tenant=tenant, payouts=payouts is not None
        )
        return files
