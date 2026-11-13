"""The `ai` pack, documents block (D34 document AI), emitted only when the spec declares `packs.ai.documents`
(validation requires the gateway, auth and rbac):

  app/ai/documents_config.py    roles, stage, review threshold, kinds and fields (data)
  app/ai/documents_models.py    ai_documents, ai_document_fields
  app/ai/documents_schemas.py   request / response models
  app/ai/documents_service.py   extraction through the gateway, anchor checks, review, concurrency-safe approve / reject
  app/ai/documents_router.py    /ai/documents/* routes
  alembic/versions/0039_ai_documents.py   the two tables

Same tenant treatment as the gateway: a `tenant_id` FK to auth_tenants on multi-tenant projects.
"""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.ai_gateway.module import ai_gateway_enabled
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_ai import documents_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/ai/documents_schemas.py.tpl",
    "app/ai/documents_service.py.tpl",
    "app/ai/documents_router.py.tpl",
)


def ai_documents_enabled(project: ProjectCtx) -> bool:
    return documents_active(project.spec) and ai_gateway_enabled(project)


class AiDocumentsModule:
    name = "ai_documents"
    manifest = ModuleManifest(id="ai_documents", version="1", depends_on=("crud", "auth", "ai_gateway"), pack="ai.documents")

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not ai_documents_enabled(project):
            return {}
        pack = project.spec.packs.ai  # type: ignore[union-attr]
        assert pack is not None and pack.documents is not None and project.auth is not None
        doc = pack.documents
        tenant = project.auth.multi_tenant
        kinds = {k.name: [(f.name, f.required) for f in k.fields] for k in sorted(doc.kinds, key=lambda k: k.name)}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/ai/documents_config.py"] = render_template(
            self._env,
            "app/ai/documents_config.py.j2",
            upload_roles=tuple(doc.upload_roles),
            review_roles=tuple(doc.review_roles),
            read_roles=tuple(doc.read_roles),
            stage=doc.stage,
            review_below_bp=doc.review_below_bp,
            max_text_chars=doc.max_text_chars,
            allow_self_review=doc.allow_self_review,
            kinds=pprint.pformat(kinds, width=96, sort_dicts=True),
        )
        files["app/ai/documents_models.py"] = render_template(self._env, "app/ai/documents_models.py.j2", tenant=tenant)
        files["alembic/versions/0039_ai_documents.py"] = render_template(
            self._env, "alembic/versions/0039_ai_documents.py.j2", tenant=tenant
        )
        return files
