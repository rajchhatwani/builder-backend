"""The `ai` pack, knowledge block (D35 knowledge library + RAG), emitted only when the spec declares `packs.ai.knowledge`
(validation requires the gateway, auth and rbac):

  app/ai/knowledge_config.py    roles, stage, chunk size, limits (data)
  app/ai/knowledge_models.py    ai_knowledge_sources (own visibility), ai_knowledge_chunks (tsvector + fake embedding)
  app/ai/knowledge_schemas.py   request / response models
  app/ai/knowledge_service.py   chunking, permission-filtered retrieval (filter in SQL before ranking), ask through the gateway
  app/ai/knowledge_router.py    /ai/knowledge/* routes
  alembic/versions/0040_ai_knowledge.py   the two tables

Same tenant treatment as the gateway: a `tenant_id` FK to auth_tenants on multi-tenant projects.
"""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.ai_gateway.module import ai_gateway_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_ai import knowledge_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/ai/knowledge_schemas.py.tpl",
    "app/ai/knowledge_service.py.tpl",
    "app/ai/knowledge_router.py.tpl",
)


def ai_knowledge_enabled(project: ProjectCtx) -> bool:
    return knowledge_active(project.spec) and ai_gateway_enabled(project)


class AiKnowledgeModule:
    name = "ai_knowledge"
    manifest = ModuleManifest(id="ai_knowledge", version="1", depends_on=("crud", "auth", "ai_gateway"), pack="ai.knowledge")

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not ai_knowledge_enabled(project):
            return {}
        pack = project.spec.packs.ai  # type: ignore[union-attr]
        assert pack is not None and pack.knowledge is not None and project.auth is not None
        kn = pack.knowledge
        tenant = project.auth.multi_tenant
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/ai/knowledge_config.py"] = render_template(
            self._env,
            "app/ai/knowledge_config.py.j2",
            manage_roles=tuple(kn.manage_roles),
            read_roles=tuple(kn.read_roles),
            known_roles=tuple(sorted(r.name for r in project.spec.auth.roles)),  # type: ignore[union-attr]
            stage=kn.stage,
            chunk_chars=kn.chunk_chars,
            max_sources=kn.max_sources,
            max_text_chars=kn.max_text_chars,
        )
        files["app/ai/knowledge_models.py"] = render_template(self._env, "app/ai/knowledge_models.py.j2", tenant=tenant)
        files["alembic/versions/0040_ai_knowledge.py"] = render_template(
            self._env, "alembic/versions/0040_ai_knowledge.py.j2", tenant=tenant
        )
        return files
