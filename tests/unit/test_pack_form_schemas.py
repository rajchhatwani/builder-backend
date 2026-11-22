"""The generated pack settings forms (frontend/src/forms/schemas) must equal the Spec* models' JSON schemas,
ignoring the hand-written `x-ui` hints, so a model change cannot silently leave a form behind."""

import json
from pathlib import Path

import pytest

from app.core.spec_models import SpecBookingPack, SpecCurrency, SpecInvoicing, SpecLedger, SpecReconciliation

SCHEMAS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "forms" / "schemas"
CASES = [
    ("ledger", SpecLedger),
    ("currency", SpecCurrency),
    ("reconciliation", SpecReconciliation),
    ("invoicing", SpecInvoicing),
    ("booking-pack", SpecBookingPack),
]


def strip_ui(node, drop=("x-ui",)):
    if isinstance(node, dict):
        return {k: strip_ui(v, drop) for k, v in node.items() if k not in drop}
    if isinstance(node, list):
        return [strip_ui(v) for v in node]
    return node


def ui_hints(node):
    if isinstance(node, dict):
        yield from ([node["x-ui"]] if "x-ui" in node else [])
        for v in node.values():
            yield from ui_hints(v)
    elif isinstance(node, list):
        for v in node:
            yield from ui_hints(v)


@pytest.mark.parametrize(("name", "model"), CASES)
def test_schema_file_matches_model(name, model):
    on_disk = json.loads((SCHEMAS / f"{name}.json").read_text())
    # `default` is compared separately: the generator adds the default_factory values Pydantic omits.
    assert strip_ui(on_disk, ("x-ui", "default")) == strip_ui(model.model_json_schema(), ("x-ui", "default"))


@pytest.mark.parametrize(("name", "model"), CASES)
def test_defaults_and_required_come_from_the_model(name, model):
    on_disk = json.loads((SCHEMAS / f"{name}.json").read_text())
    assert on_disk.get("required", []) == model.model_json_schema().get("required", [])
    defaults = {k: f.get_default(call_default_factory=True) for k, f in model.model_fields.items() if not f.is_required()}
    for k, v in defaults.items():
        shown = on_disk["properties"][k].get("default", "MISSING")
        expected = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
        assert shown == expected, k


@pytest.mark.parametrize(("name", "model"), CASES)
def test_ui_hints_name_real_fields(name, model):
    on_disk = json.loads((SCHEMAS / f"{name}.json").read_text())
    for hint in ui_hints(on_disk):
        assert set(hint) <= {"order", "hidden", "showWhen", "widget", "label", "optional", "itemLabel", "help"}
