"""The `documents` feature: PDF documents rendered by the generated API.

Emitted only when the spec has an enabled `documents` block with at least one template:

  app/documents/engine.py   the PDF engine, copied byte for byte from app/core/doc_engine.py
  app/documents/data.py     the templates, as data
  app/documents/router.py   GET /documents and one render route per template
  tests/test_documents.py   access, determinism, escaping, recomputed totals, limits
  docs/DOCUMENTS.md         how to call it, how to edit a template, what is and is not supported
"""

import hashlib
import pprint
from pathlib import Path
from typing import Any

from app.core import doc_engine
from app.core.generator.base import FileTree
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.render import make_environment, render_template
from app.core.validation_documents import documents_active

_TEMPLATES = Path(__file__).parent / "templates"


def engine_source() -> str:
    """The engine exactly as the builder runs it (line endings normalised, nothing added)."""
    return Path(doc_engine.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")


def render_data(templates: list[dict[str, Any]]) -> str:
    body = pprint.pformat({t["id"]: t for t in templates}, width=88, sort_dicts=True)
    return (
        '"""PDF templates (generated from the spec: change them in the builder).\n\n'
        "Plain data read by app/documents/router.py; the engine never evaluates anything in it\n"
        'except the placeholders documented in docs/DOCUMENTS.md."""\n\n'
        f"TEMPLATES = {body}\n"
    )


class DocumentsModule:
    name = "documents"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        block = documents_active(project.spec)
        if block is None or project.auth is None:
            return {}
        by_name: dict[str, EntityCtx] = {e.name: e for e in project.entities}
        templates: list[dict[str, Any]] = []
        for t in block.templates:
            entity = by_name.get(t.entity) if t.entity else None
            templates.append(
                {
                    "id": t.id,
                    "title": t.title or t.id,
                    "kind": t.kind,
                    "entity": entity.name if entity is not None else None,
                    "compute": t.compute,
                    "roles": sorted(set(t.roles)),
                    "template": t.template,
                }
            )
        bound = [
            (t, by_name[t["entity"]]) for t in templates if t["entity"] is not None
        ]
        entities_used = sorted({e.table: e for _, e in bound}.values(), key=lambda e: e.table)
        engine_text = engine_source()
        context = {
            "templates": templates,
            "bound": bound,
            "entities_used": entities_used,
            "rate_limit": block.rate_limit,
            "project_name": project.name,
            "engine_sha256": hashlib.sha256(engine_text.encode("utf-8")).hexdigest(),
            "limits": {
                "blocks": doc_engine.MAX_BLOCKS,
                "rows": doc_engine.MAX_TABLE_ROWS,
                "text": doc_engine.MAX_TEXT,
                "pages": doc_engine.MAX_PAGES,
                "image_kb": doc_engine.MAX_IMAGE_BYTES // 1000,
            },
        }

        def render(template: str) -> str:
            return render_template(self._env, template, **context)

        return {
            "app/documents/__init__.py": "",
            "app/documents/engine.py": engine_text,
            "app/documents/data.py": render_data(templates),
            "app/documents/router.py": render("app/documents/router.py.j2"),
            "tests/test_documents.py": render("tests/test_documents.py.j2"),
            "docs/DOCUMENTS.md": render("docs/DOCUMENTS.md.j2"),
        }
