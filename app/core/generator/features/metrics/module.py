"""The `metrics` feature: GET /metrics and GET /metrics/{key} in the generated app. Emitted only when the
spec has `metrics_layer.definitions`.

  app/metrics/definitions.py  the definitions (data) and the field types they are computed in
  app/metrics/engine.py       the deterministic rules, computed in SQL through the caller's row scope
  app/metrics/router.py       the two routes (list access of the entity decides; hidden fields are refused)
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.features.realtime.module import list_access
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.metrics import parse_metric
from app.core.validation_realtime import metrics_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/metrics/__init__.py.tpl",
    "app/metrics/engine.py.tpl",
)


def metrics_definitions(project: ProjectCtx) -> list[dict[str, Any]]:
    """The validated definitions, normalised (every key present), sorted by key. Empty when off."""
    if not metrics_active(project.spec):
        return []
    assert project.spec.metrics_layer is not None
    out = []
    for raw in project.spec.metrics_layer.definitions:
        d = parse_metric(raw)
        out.append(
            {
                "key": d.key,
                "label": d.label,
                "entity": d.entity,
                "agg": d.agg,
                "field": d.field,
                "filter": [{"field": f.field, "op": f.op, "value": f.value} for f in d.filter],
                "group_by": d.group_by,
                "unit": d.unit,
            }
        )
    return sorted(out, key=lambda m: m["key"])


class MetricsModule:
    name = "metrics"
    manifest = ModuleManifest(id="metrics", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        definitions = metrics_definitions(project)
        if not definitions:
            return {}
        used = sorted({d["entity"] for d in definitions})
        spec_entities = {e.name: e for e in project.spec.entities}
        types = {
            name: {f.name: str(getattr(f.type, "value", f.type)) for f in spec_entities[name].fields}
            for name in used
        }
        entities: list[EntityCtx] = [project.entity_by_name[name] for name in used]
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/metrics/definitions.py"] = (
            '"""Metric definitions (generated from the spec: change them in the builder). Plain data."""\n\n'
            "from typing import Any\n\n"
            f"METRICS: dict[str, dict[str, Any]] = {pprint.pformat({d['key']: d for d in definitions}, width=96, sort_dicts=True)}\n\n"
            f"FIELD_TYPES: dict[str, dict[str, str]] = {pprint.pformat(types, width=96, sort_dicts=True)}\n"
        )
        listed = [list_access(e) for e in entities]
        files["app/metrics/router.py"] = render_template(
            self._env,
            "app/metrics/router.py.j2",
            entities=listed,
            auth=project.auth is not None,
            guarded=project.auth is not None and any(e.guarded for e in project.entities),
        )
        return files
