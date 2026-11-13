"""The `ai` pack, gateway block (D33 LLM gateway), emitted only when the spec declares `packs.ai.gateway`
(validation requires auth with rbac):

  app/ai/config.py      roles, region, zero retention, budget, price table (UNVERIFIED), providers, stages (data)
  app/ai/models.py      ai_calls (the cost ledger), ai_budget_periods (spent and reserved micro-USD, locked row)
  app/ai/providers.py   the deterministic FAKE provider (no network) and its test switches
  app/ai/schemas.py     request / response models (StrictInt)
  app/ai/service.py     route by stage, reserve worst case under a row lock, call, settle or release, idempotency
  app/ai/router.py      /ai/* routes
  alembic/versions/0038_ai_gateway.py   the two tables

Same tenant treatment as booking: a `tenant_id` FK to auth_tenants on multi-tenant projects.
"""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_ai import AI_PRICES, gateway_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/ai/__init__.py.tpl",
    "app/ai/schemas.py.tpl",
    "app/ai/providers.py.tpl",
    "app/ai/service.py.tpl",
    "app/ai/router.py.tpl",
)


def ai_gateway_enabled(project: ProjectCtx) -> bool:
    return gateway_active(project.spec) and project.auth is not None


class AiGatewayModule:
    name = "ai_gateway"
    manifest = ModuleManifest(id="ai_gateway", version="1", depends_on=("crud", "auth"), pack="ai.gateway")

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not ai_gateway_enabled(project):
            return {}
        pack = project.spec.packs.ai  # type: ignore[union-attr]
        assert pack is not None and pack.gateway is not None and project.auth is not None
        gw = pack.gateway
        tenant = project.auth.multi_tenant
        providers = {p.name: {"kind": p.kind, "byo_key_env": p.byo_key_env} for p in sorted(gw.providers, key=lambda p: p.name)}
        stages = {
            s.name: {
                "provider": s.provider,
                "model": s.model,
                "max_output_tokens": s.max_output_tokens,
                "fallback_model": s.fallback_model,
            }
            for s in sorted(gw.stages, key=lambda s: s.name)
        }
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/ai/config.py"] = render_template(
            self._env,
            "app/ai/config.py.j2",
            call_roles=tuple(gw.roles.call_roles),
            read_roles=tuple(gw.roles.read_roles),
            manage_roles=tuple(gw.roles.manage_roles),
            region=gw.region,
            zero_retention=gw.zero_retention,
            period=gw.budget.period,
            limit=gw.budget.limit_micro_usd,
            cap=gw.budget.per_call_cap_micro_usd,
            prices=pprint.pformat(dict(sorted(AI_PRICES.items())), width=96, sort_dicts=True),
            providers=pprint.pformat(providers, width=96, sort_dicts=True),
            stages=pprint.pformat(stages, width=96, sort_dicts=True),
            tenant=tenant,
        )
        files["app/ai/models.py"] = render_template(self._env, "app/ai/models.py.j2", tenant=tenant)
        files["alembic/versions/0038_ai_gateway.py"] = render_template(
            self._env, "alembic/versions/0038_ai_gateway.py.j2", tenant=tenant
        )
        return files
