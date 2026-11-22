"""Dump the JSON Schemas of the operations pack settings forms (CP-6G) from the Spec* models (read-only).

Run from the repo root:  PYTHONPATH=. uv run python frontend/scripts/dump_form_schemas_ops.py
Writes frontend/src/forms/schemas/{geo,location,matching,prediction}.json. The `x-ui` hints are the only hand-written part.
"""

import json
from pathlib import Path

from app.core.spec_models import SpecGeo, SpecLocation, SpecMatchWeights, SpecMatching, SpecPrediction

OUT = Path(__file__).resolve().parent.parent / "src" / "forms" / "schemas"
CSV = {"widget": "csv"}


def prop(schema: dict, name: str) -> dict:
    return schema["properties"][name]


def roles(schema: dict, *names: str) -> None:
    for n in names:
        prop(schema, n)["x-ui"] = dict(CSV)


def with_defaults(model, extra: dict | None = None) -> dict:
    """The model's JSON schema, plus the `default` Pydantic leaves out for default_factory fields (so the form starts
    from the real defaults, e.g. read_roles ["admin"], not from empty = any signed-in user)."""
    schema = model.model_json_schema()
    nested = {m.__name__: m for m in (extra or {}).values()}
    for node, cls in [(schema, model), *[(schema["$defs"][n], c) for n, c in nested.items() if n in schema.get("$defs", {})]]:
        for fname, field in cls.model_fields.items():
            if field.default_factory is not None:
                v = field.get_default(call_default_factory=True)
                node["properties"][fname]["default"] = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
    return schema


geo = with_defaults(SpecGeo)
roles(geo, "read_roles", "write_roles")
# The provider is always "fake" (no outbound calls): kept in the saved block, never shown or edited.
prop(geo, "provider")["x-ui"] = {"hidden": True}
geo["x-ui"] = {"order": ["read_roles", "write_roles", "grid_cell_micro", "max_places", "max_geofences", "max_polygon_vertices", "max_radius_m", "provider"]}

location = with_defaults(SpecLocation)
roles(location, "read_roles", "write_roles")

matching = with_defaults(SpecMatching, {1: SpecMatchWeights})
roles(matching, "read_roles", "assign_roles")
prop(matching, "weights")["x-ui"] = {"label": "Score weights"}

prediction = with_defaults(SpecPrediction)
roles(prediction, "read_roles", "write_roles")

for name, schema in (("geo", geo), ("location", location), ("matching", matching), ("prediction", prediction)):
    (OUT / f"{name}.json").write_text(json.dumps(schema, indent=2, sort_keys=False) + "\n")
    print("wrote", name)
