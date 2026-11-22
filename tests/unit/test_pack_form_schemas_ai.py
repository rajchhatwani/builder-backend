"""The generated AI pack settings forms (frontend/src/forms/schemas/ai-*.json) must equal the SpecAi* models' JSON
schemas, ignoring the hand-written `x-ui` hints, so a model change cannot silently leave a form behind."""

import json
from pathlib import Path

import pytest

from app.core.spec_models import (
    SpecAiAgents,
    SpecAiDocuments,
    SpecAiEvals,
    SpecAiGateway,
    SpecAiKnowledge,
)

SCHEMAS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "forms" / "schemas"
CASES = [
    ("ai-gateway", SpecAiGateway),
    ("ai-documents", SpecAiDocuments),
    ("ai-knowledge", SpecAiKnowledge),
    ("ai-agents", SpecAiAgents),
    ("ai-evals", SpecAiEvals),
]
ALLOWED_HINTS = {"order", "hidden", "showWhen", "widget", "label", "optional", "itemLabel", "help"}
SECRET_WORDS = (
    "secret",
    "password",
    "api_key",
    "apikey",
    "private_key",
    "access_token",
    "auth_token",
)


def strip_ui(node, drop=("x-ui",)):
    if isinstance(node, dict):
        return {k: strip_ui(v, drop) for k, v in node.items() if k not in drop}
    if isinstance(node, list):
        return [strip_ui(v, drop) for v in node]
    return node


def walk(node):
    """Every dict in the schema, with the x-ui hint (if any) and the property names around it."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def load(name):
    return json.loads((SCHEMAS / f"{name}.json").read_text())


@pytest.mark.parametrize(("name", "model"), CASES)
def test_schema_file_matches_model(name, model):
    # `default` is compared separately: the generator adds the default_factory values Pydantic omits.
    assert strip_ui(load(name), ("x-ui", "default")) == strip_ui(
        model.model_json_schema(), ("x-ui", "default")
    )


@pytest.mark.parametrize(("name", "model"), CASES)
def test_defaults_and_required_come_from_the_model(name, model):
    on_disk = load(name)
    assert on_disk.get("required", []) == model.model_json_schema().get("required", [])
    for k, f in model.model_fields.items():
        if f.is_required():
            continue
        v = f.get_default(call_default_factory=True)
        expected = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
        assert on_disk["properties"][k].get("default", "MISSING") == expected, k


@pytest.mark.parametrize(("name", "model"), CASES)
def test_ui_hints_are_known_and_nothing_is_hidden(name, model):
    """A form must show every field of its block: no `hidden` hint anywhere, and only known hint keys."""
    for node in walk(load(name)):
        hint = node.get("x-ui")
        if hint is not None:
            assert set(hint) <= ALLOWED_HINTS
            assert not hint.get("hidden")


@pytest.mark.parametrize(("name", "model"), CASES)
def test_ui_hints_order_names_real_fields(name, model):
    for node in walk(load(name)):
        order = (node.get("x-ui") or {}).get("order")
        if order is not None:
            assert set(order) <= set(node["properties"])


@pytest.mark.parametrize(("name", "model"), CASES)
def test_no_secret_is_a_form_field(name, model):
    for node in walk(load(name)):
        for prop in node.get("properties", {}):
            assert not any(w in prop.lower() for w in SECRET_WORDS), prop
