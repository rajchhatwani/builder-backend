"""The `ai` pack, evals block (D38 eval harness), emitted only when the spec declares `packs.ai.evals`
(validation requires the agents block):

  app/ai/evals_config.py    roles and the suites (data)
  app/ai/evals_models.py    ai_eval_runs
  app/ai/evals_schemas.py   response models
  app/ai/evals_service.py   runs every case of a suite through the agent runtime in dry mode, scores it
  app/ai/evals_router.py    /ai/evals/* routes
  alembic/versions/0042_ai_evals.py   the table
"""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.ai_agents.module import ai_agents_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_ai import evals_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/ai/evals_schemas.py.tpl",
    "app/ai/evals_service.py.tpl",
    "app/ai/evals_router.py.tpl",
)


def ai_evals_enabled(project: ProjectCtx) -> bool:
    return evals_active(project.spec) and ai_agents_enabled(project)


class AiEvalsModule:
    name = "ai_evals"
    manifest = ModuleManifest(id="ai_evals", version="1", depends_on=("crud", "auth", "ai_gateway", "ai_agents"), pack="ai.evals")

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not ai_evals_enabled(project):
            return {}
        pack = project.spec.packs.ai  # type: ignore[union-attr]
        assert pack is not None and pack.evals is not None and project.auth is not None
        ev = pack.evals
        tenant = project.auth.multi_tenant
        suites = {
            s.name: {
                "agent": s.agent,
                "pass_bp": s.pass_bp,
                "cases": [
                    {"name": c.name, "goal": c.goal, "expect_actions": list(c.expect_actions), "forbid_actions": list(c.forbid_actions)}
                    for c in s.cases
                ],
            }
            for s in sorted(ev.suites, key=lambda s: s.name)
        }
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/ai/evals_config.py"] = render_template(
            self._env,
            "app/ai/evals_config.py.j2",
            run_roles=tuple(ev.run_roles),
            suites=pprint.pformat(suites, width=96, sort_dicts=True),
        )
        files["app/ai/evals_models.py"] = render_template(self._env, "app/ai/evals_models.py.j2", tenant=tenant)
        files["alembic/versions/0042_ai_evals.py"] = render_template(
            self._env, "alembic/versions/0042_ai_evals.py.j2", tenant=tenant
        )
        return files
