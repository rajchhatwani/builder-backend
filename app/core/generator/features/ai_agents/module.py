"""The `ai` pack, agents block (D37 agent runtime), emitted only when the spec declares `packs.ai.agents`
(validation requires the gateway, auth and rbac):

  app/ai/agents_config.py    roles, the action registry, the agents, the writable entity fields (data)
  app/ai/agents_models.py    ai_agent_runs, ai_agent_proposals
  app/ai/agents_schemas.py   request / response models
  app/ai/agents_service.py   the run (model call only through the gateway), the autonomy dial, approve / reject / ...
  app/ai/agents_router.py    /ai/agents/* routes
  alembic/versions/0041_ai_agents.py   the two tables

Same tenant treatment as the gateway: a `tenant_id` FK to auth_tenants on multi-tenant projects.
"""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.ai_gateway.module import ai_gateway_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_ai import agents_active, evals_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/ai/agents_schemas.py.tpl",
    "app/ai/agents_service.py.tpl",
    "app/ai/agents_router.py.tpl",
)


def ai_agents_enabled(project: ProjectCtx) -> bool:
    return agents_active(project.spec) and ai_gateway_enabled(project)


class AiAgentsModule:
    name = "ai_agents"
    manifest = ModuleManifest(id="ai_agents", version="1", depends_on=("crud", "auth", "ai_gateway"), pack="ai.agents")

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not ai_agents_enabled(project):
            return {}
        pack = project.spec.packs.ai  # type: ignore[union-attr]
        assert pack is not None and pack.agents is not None and project.auth is not None
        ag = pack.agents
        tenant = project.auth.multi_tenant
        actions = {
            a.name: {
                "kind": a.kind,
                "description": a.description,
                "risk": a.risk,
                "max_autonomy": a.max_autonomy,
                "entity": a.entity,
                "fields": list(a.fields),
            }
            for a in sorted(ag.actions, key=lambda a: a.name)
        }
        agents = {
            a.name: {
                "stage": a.stage,
                "actions": list(a.actions),
                "autonomy": a.autonomy,
                "max_actions_per_run": a.max_actions_per_run,
                "require_eval": a.require_eval,
            }
            for a in sorted(ag.agents, key=lambda a: a.name)
        }
        tables = {a.entity for a in ag.actions if a.kind == "entity_create" and a.entity is not None}
        entities: dict[str, dict[str, dict[str, object]]] = {}
        for entity in sorted(project.spec.entities, key=lambda e: e.table_name):
            if entity.table_name not in tables:
                continue
            writable = {f for a in ag.actions if a.entity == entity.table_name for f in a.fields}
            entities[entity.table_name] = {
                f.name: {
                    "type": f.type,
                    "required": f.required,
                    "max_length": f.max_length,
                    "enum": list(f.enum_values) if f.enum_values else None,
                    "min": f.min_value,
                    "max": f.max_value,
                }
                for f in entity.fields
                if f.name in writable
            }
        create_roles: dict[str, tuple[str, ...]] = {}
        for table in sorted(tables):
            entity_name = next((e.name for e in project.spec.entities if e.table_name == table), None)
            roles: set[str] = set()
            for perm in project.spec.auth.permissions:  # type: ignore[union-attr]
                if perm.entity == entity_name and perm.operation == "create":
                    roles.update(perm.roles)
            create_roles[table] = tuple(sorted(roles))
        # table -> how to reach the entity's own repository (the same create path as its POST route) and what the
        # agent runtime must refuse because it needs a request context (abac / pbac policy decisions)
        runtime: dict[str, dict[str, object]] = {}
        for table in sorted(tables):
            ctx = next((e for e in project.entity_by_name.values() if e.table == table), None)
            if ctx is None:
                continue
            runtime[table] = {
                "module": f"app.crud.{ctx.table}",
                "repository": f"{ctx.name}Repository",
                "entity": ctx.name,
                "policy": ctx.policy,
                "guarded": ctx.guarded,
                "numbered": bool(ctx.numbered),
            }
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/ai/agents_config.py"] = render_template(
            self._env,
            "app/ai/agents_config.py.j2",
            run_roles=tuple(ag.roles.run_roles),
            approve_roles=tuple(ag.roles.approve_roles),
            read_roles=tuple(ag.roles.read_roles),
            known_roles=tuple(sorted(r.name for r in project.spec.auth.roles)),  # type: ignore[union-attr]
            allow_self_approval=ag.allow_self_approval,
            evals=evals_active(project.spec),
            actions=pprint.pformat(actions, width=96, sort_dicts=True),
            agents=pprint.pformat(agents, width=96, sort_dicts=True),
            entities=pprint.pformat(entities, width=96, sort_dicts=True),
            create_roles=pprint.pformat(create_roles, width=96, sort_dicts=True),
            runtime=pprint.pformat(runtime, width=96, sort_dicts=True),
        )
        files["app/ai/agents_models.py"] = render_template(self._env, "app/ai/agents_models.py.j2", tenant=tenant)
        files["alembic/versions/0041_ai_agents.py"] = render_template(
            self._env, "alembic/versions/0041_ai_agents.py.j2", tenant=tenant
        )
        return files
