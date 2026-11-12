"""The money pack's `currency` block (D5), emitted only when the spec declares `packs.money.currency`:

  app/money/__init__.py   the packs this project declares (PACKS)
  app/money/settings.py   the declared currencies, rounding mode and static tax rates (data from the spec)
  app/money/currency.py   ISO 4217 exponents, banker's rounding, largest-remainder allocation (integers only)
  app/money/tax.py        a static tax adapter (no network): exclusive and inclusive quotes in minor units

Everything works on integers (minor units) and Decimal; there is no float anywhere in the emitted code.
"""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_packs import MONEY_EXPONENTS, currency_active, declared_packs

_TEMPLATES = Path(__file__).parent / "templates"


class MoneyCurrencyModule:
    name = "money_currency"
    manifest = ModuleManifest(id="money_currency", version="1", depends_on=("crud",), pack="money.currency")

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not currency_active(project.spec):
            return {}
        cfg = project.spec.packs.money.currency  # type: ignore[union-attr]
        assert cfg is not None
        rates = dict(sorted(cfg.tax.rates_bp.items())) if cfg.tax else {}
        return {
            "app/money/__init__.py": render_template(
                self._env, "app/money/__init__.py.j2", packs=declared_packs(project.spec)
            ),
            "app/money/settings.py": render_template(
                self._env,
                "app/money/settings.py.j2",
                currencies=tuple(sorted(cfg.currencies)),
                rates=pprint.pformat(rates, width=96, sort_dicts=True),
            ),
            "app/money/currency.py": render_template(
                self._env,
                "app/money/currency.py.j2",
                exponents=pprint.pformat(dict(sorted(MONEY_EXPONENTS.items())), width=96, sort_dicts=True),
            ),
            "app/money/tax.py": read_verbatim(_TEMPLATES, "app/money/tax.py.tpl"),
        }
