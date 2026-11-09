"""The `realtime` feature: GET /realtime/stream (Server-Sent Events) for the records of the generated app.
Emitted only when the spec has `realtime.enabled` (and at least one entity can be streamed).

  app/realtime/protocol.py  envelope, SSE frames, Last-Event-ID, stale-cursor rule, stream cap, reconnect throttle
  app/realtime/models.py    rt_events (ids only, never field values) and rt_floor (the prune floor)
  app/realtime/service.py   publish (same transaction, ordered by an advisory lock), replay, prune, scope filter
  app/realtime/hooks.py     the repository hook (after_save) every streamed entity gets
  app/realtime/router.py    the stream: replay, live tail, per-caller filter, heartbeat, max age, resync
  app/realtime/prune.py     `python -m app.realtime.prune`
  alembic/versions/0022_realtime.py
"""

from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_realtime import realtime_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/realtime/__init__.py.tpl",
    "app/realtime/protocol.py.tpl",
    "app/realtime/models.py.tpl",
    "app/realtime/service.py.tpl",
    "app/realtime/hooks.py.tpl",
    "app/realtime/prune.py.tpl",
)


def realtime_entities(project: ProjectCtx) -> tuple[EntityCtx, ...]:
    """Entities that publish events: a list operation (otherwise nobody could receive them) and role-based
    access (abac / pbac policies are refused by the spec validation)."""
    if not realtime_active(project.spec):
        return ()
    return tuple(e for e in project.entities if "list" in e.ops and not e.policy)


def list_access(e: EntityCtx) -> dict[str, Any]:
    """How the stream and metrics call an entity's `list` access dependency."""
    access = next((a for a in e.access if a.op == "list"), None)
    return {
        "name": e.name,
        "table": e.table,
        "scoped": access is not None,
        "needs_user": access is not None and access.needs_user,
    }


class RealtimeModule:
    name = "realtime"
    manifest = ModuleManifest(id="realtime", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        entities = realtime_entities(project)
        if not entities:
            return {}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/realtime/router.py"] = render_template(
            self._env,
            "app/realtime/router.py.j2",
            entities=[list_access(e) for e in entities],
            auth=project.auth is not None,
            max_stream=300,
        )
        files["alembic/versions/0022_realtime.py"] = render_template(
            self._env, "alembic/versions/0022_realtime.py.j2"
        )
        return files
