"""Dump the JSON Schemas for the F2-1 forms-preview page from the backend's Pydantic models (read-only).

Run from the repo root:  PYTHONPATH=. uv run python frontend/scripts/dump_form_schemas.py
Writes frontend/src/forms/schemas/*.json. The `x-ui` hints are the only hand-written part.
"""

import json
from pathlib import Path

from app.core.spec_models import (
    SpecBookingPack,
    SpecCurrency,
    SpecBookingCancellation,
    SpecBookingKind,
    SpecInvoicing,
    SpecLedger,
    SpecPayouts,
    SpecReconciliation,
    SpecTax,
)
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

# --- Packs blocks (CP-6F): derived from the Spec* models; titles/descriptions stay the model's own. ---
CSV = {"widget": "csv"}


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


ledger = with_defaults(SpecLedger)
roles(ledger, "read_roles", "post_roles")

currency = with_defaults(SpecCurrency, {1: SpecTax})
prop(currency, "currencies")["x-ui"] = dict(CSV)
prop(currency, "tax")["x-ui"] = {"optional": True, "label": "Tax rates"}
currency["$defs"]["SpecTax"]["properties"]["rates_bp"]["x-ui"] = {
    "help": 'JSON object: tax name -> rate in basis points (1 bp = 0.01%), integers only, e.g. {"VAT": 2000}'}

recon = with_defaults(SpecReconciliation)
roles(recon, "read_roles", "run_roles")

invoicing = with_defaults(SpecInvoicing, {1: SpecPayouts})
roles(invoicing, "read_roles", "write_roles")
prop(invoicing, "aging_buckets_days")["x-ui"] = dict(CSV)
prop(invoicing, "payouts")["x-ui"] = {"optional": True, "label": "Payouts"}

booking = with_defaults(SpecBookingPack, {1: SpecBookingKind, 2: SpecBookingCancellation})
roles(booking, "read_roles", "book_roles", "manage_roles")
prop(booking, "kinds")["x-ui"] = {"itemLabel": "Kind"}
kind = booking["$defs"]["SpecBookingKind"]
kind["x-ui"] = {"order": ["name", "mode", "timezone", "slot_minutes", "capacity", "min_minutes", "max_minutes", "schedule"]}
kind["properties"]["schedule"]["x-ui"] = {
    "showWhen": {"field": "mode", "equals": "slot"},
    "help": 'JSON object: weekday (mon..sun) -> list of windows, e.g. {"mon": [{"start": "09:00", "end": "17:00"}]}'}
kind["properties"]["slot_minutes"]["x-ui"] = {"showWhen": {"field": "mode", "equals": "slot"}}
kind["properties"]["capacity"]["x-ui"] = {"showWhen": {"field": "mode", "equals": "pool"}}
for k in ("min_minutes", "max_minutes"):
    kind["properties"][k]["x-ui"] = {"showWhen": {"field": "mode", "in": ["range", "pool"]}}

PACK_SCHEMAS = (("ledger", ledger), ("currency", currency), ("reconciliation", recon),
                ("invoicing", invoicing), ("booking-pack", booking))

for name, schema in (("observability", obs), ("lists", lists), ("storage", storage), *PACK_SCHEMAS):
    (OUT / f"{name}.json").write_text(json.dumps(schema, indent=2, sort_keys=False) + "\n")
    print("wrote", name)
