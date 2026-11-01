"""Dump the JSON Schemas for the F2-1 forms-preview page from the backend's Pydantic models (read-only).

Run from the repo root:  PYTHONPATH=. uv run python frontend/scripts/dump_form_schemas.py
Writes frontend/src/forms/schemas/*.json. The `x-ui` hints are the only hand-written part.
"""

import json
from pathlib import Path

from app.schemas.behavior import ListsWrite
from app.schemas.observability import ObservabilityWrite
from app.schemas.storage import StorageConfigWrite

OUT = Path(__file__).resolve().parent.parent / "src" / "forms" / "schemas"


def hint(schema: dict, path: list[str], ui: dict) -> None:
    node = schema
    for p in path:
        node = node["properties"][p] if "properties" in node else node
    node["x-ui"] = {**node.get("x-ui", {}), **ui}


def prop(schema: dict, name: str) -> dict:
    return schema["properties"][name]


obs = ObservabilityWrite.model_json_schema()
obs["title"] = "Observability"
del obs["properties"]["expected_version"]
obs["x-ui"] = {"order": ["enabled", "service_name", "sample_ratio", "metrics", "db_spans", "local_stack",
                         "expected_rps", "exclude_paths", "extra_redact_keys"]}
for k in ("service_name", "sample_ratio", "metrics", "db_spans", "local_stack", "expected_rps",
          "exclude_paths", "extra_redact_keys"):
    prop(obs, k)["x-ui"] = {"showWhen": {"field": "enabled", "equals": True}}
for k in ("exclude_paths", "extra_redact_keys"):
    prop(obs, k)["x-ui"]["widget"] = "csv"

lists = ListsWrite.model_json_schema()
lists["title"] = "Lists"
del lists["properties"]["expected_version"]
list_body = lists["$defs"]["ListBody"]
list_body["x-ui"] = {"order": ["name", "label", "max_items", "edit_roles", "items"]}
list_body["properties"]["edit_roles"]["x-ui"] = {"widget": "csv"}
list_body["properties"]["items"]["x-ui"] = {"itemLabel": "Item"}
lists["properties"]["lists"]["x-ui"] = {"itemLabel": "List"}
lists["$defs"]["ListItemBody"]["x-ui"] = {"order": ["value", "label", "color", "locked"]}

storage = StorageConfigWrite.model_json_schema()
storage["title"] = "Storage"
storage["x-ui"] = {"order": ["backend", "bucket", "region", "key_prefix", "download_mode", "max_file_mb",
                             "user_quota_mb", "uploads_per_hour", "allow_inline_images", "allowed_types",
                             "roles", "security"]}
prop(storage, "region")["x-ui"] = {"showWhen": {"field": "backend", "equals": "s3"}}
prop(storage, "allowed_types")["x-ui"] = {"widget": "csv"}
for k in storage["$defs"]["StorageRoles"]["properties"].values():
    k["x-ui"] = {"widget": "csv"}

for name, schema in (("observability", obs), ("lists", lists), ("storage", storage)):
    (OUT / f"{name}.json").write_text(json.dumps(schema, indent=2, sort_keys=False) + "\n")
    print("wrote", name)
