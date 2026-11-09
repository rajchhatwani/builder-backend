"""The `search` feature: GET /<entity path>/search?q=&limit= for entities with a `list` operation and
searchable fields. Emitted only when at least one entity qualifies (otherwise nothing changes).

  app/search/config.py    SEARCH_BACKEND = fts (default) | opensearch | opensearch-fake (tests only)
  app/search/adapters.py  engine interface, OpenSearch over HTTP, in-memory fake
  app/search/service.py   the query: always inside the entity's list access scope; hidden fields excluded
  app/search/hooks.py     index sync (after_commit; no-op with fts)
  app/search/router.py    one route per qualifying entity (mounted before the entity routers, so
                          `/search` is not read as an item id)
"""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template

_TEMPLATES = Path(__file__).parent / "templates"
MAX_LIMIT = 100
MAX_Q = 200

_VERBATIM = (
    "app/search/__init__.py.tpl",
    "app/search/adapters.py.tpl",
    "app/search/config.py.tpl",
    "app/search/hooks.py.tpl",
    "app/search/service.py.tpl",
)


def search_entities(project: ProjectCtx) -> tuple[EntityCtx, ...]:
    """Entities that get a search route: a list operation and at least one searchable field."""
    return tuple(e for e in project.entities if "list" in e.ops and e.searchable)


class SearchModule:
    name = "search"
    manifest = ModuleManifest(id="search", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        entities = search_entities(project)
        if not entities:
            return {}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/search/router.py"] = render_template(
            self._env,
            "app/search/router.py.j2",
            entities=entities,
            with_access=any("list" in e.access_ops for e in entities),
            max_q=MAX_Q,
            max_limit=MAX_LIMIT,
        )
        files["app/search/reindex.py"] = render_template(self._env, "app/search/reindex.py.j2", entities=entities)
        return files
