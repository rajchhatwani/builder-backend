"""CP-5D-AI: the AI pack, documents block (D34). Spec rules, emission only when declared, migration 0039, tenant treatment,
the generated pure parts executed (anchor check, fake extraction). Database behaviour is proven by
tests/e2e/test_ai_documents_stack.py."""

import ast
import asyncio
import json
import types
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.generator.engine import pack_registry
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_ai import ai_tables
from app.core.validation_packs import declared_packs

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw() -> dict[str, Any]:
    return json.loads((FIXTURES / "ai_documents_knowledge.json").read_text(encoding="utf-8"))


def _files(raw: dict[str, Any] | None = None) -> dict[str, str]:
    return generate(Spec.model_validate(raw or _raw()))


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _pure(source: str, names: set[str], **ns: Any) -> types.ModuleType:
    tree = ast.parse(source)
    wanted = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    module = types.ModuleType("pure")
    module.__dict__.update(ns)
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "pure", "exec"), module.__dict__)  # noqa: S102
    return module


def _parse_module(source: str) -> types.ModuleType:
    import re

    return _pure(source, {"parse_field", "_normal", "_supported"}, _t=__import__("typing"), re=re, _STRIP=re.compile(r"[\s,$\u20ac\u00a3]"))


def test_the_fixture_is_valid_and_declares_all_three_ai_blocks() -> None:
    spec = Spec.model_validate(_raw())
    assert validate(spec) == []
    assert declared_packs(spec) == ("ai.documents", "ai.gateway", "ai.knowledge")
    assert ai_tables(spec) == ("ai_calls", "ai_budget_periods", "ai_documents", "ai_document_fields", "ai_knowledge_sources", "ai_knowledge_chunks")
    assert {"ai.documents", "ai.knowledge"} <= set(pack_registry())


def test_documents_are_emitted_only_when_declared() -> None:
    raw = _raw()
    del raw["packs"]["ai"]["documents"]
    files = _files(raw)
    assert not [p for p in files if "documents" in p] and any("knowledge" in p for p in files)
    assert "_ai_documents_router" not in files["app/main.py"]
    assert ai_tables(Spec.model_validate(raw)) == ("ai_calls", "ai_budget_periods", "ai_knowledge_sources", "ai_knowledge_chunks")
    del raw["packs"]["ai"]["knowledge"]
    assert not [p for p in _files(raw) if "knowledge" in p]


def test_the_files_wiring_and_conftest() -> None:
    files = _files()
    for path in ("app/ai/documents_config.py", "app/ai/documents_models.py", "app/ai/documents_router.py", "alembic/versions/0039_ai_documents.py"):
        assert path in files
    assert "_ai_documents_router" in files["app/main.py"] and "documents_models" in files["app/models/__init__.py"]
    for table in ("ai_documents", "ai_document_fields", "ai_knowledge_sources", "ai_knowledge_chunks"):
        assert f" {table}," in files["tests/conftest.py"]
    config = files["app/ai/documents_config.py"]
    assert "REVIEW_BELOW_BP = 8000" in config and "'total', True" in config and "STAGE = 'extract'" in config
    migration = files["alembic/versions/0039_ai_documents.py"]
    assert 'down_revision: str | None = "0038"' in migration and "tenant_id" in migration
    assert files["alembic/versions/0040_ai_knowledge.py"].count('down_revision: str | None = "0039"') == 1


def test_single_tenant_has_no_tenant_column() -> None:
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for permission in raw["auth"]["permissions"]:
        permission.pop("row_rule")
    files = _files(raw)
    assert "tenant_id" not in files["app/ai/documents_models.py"] and "tenant_id" not in files["alembic/versions/0039_ai_documents.py"]


def test_validation_rules() -> None:
    def with_doc(**patch: Any) -> set[str]:
        raw = _raw()
        raw["packs"]["ai"]["documents"].update(patch)
        return _codes(raw)

    assert "unknown_stage" in with_doc(stage="nope")
    assert "unknown_role" in with_doc(review_roles=["wizard"])
    assert "empty" in with_doc(review_roles=[])
    assert "out_of_range" in with_doc(review_below_bp=10001)
    assert "empty" in with_doc(kinds=[])
    assert "duplicate" in with_doc(kinds=[{"name": "a", "fields": [{"name": "x"}, {"name": "x"}]}])
    assert "invalid_identifier" in with_doc(kinds=[{"name": "a", "fields": [{"name": "Bad"}]}])
    raw = _raw()
    del raw["packs"]["ai"]["gateway"]
    assert "needs_gateway" in _codes(raw)


def test_the_anchor_check_accepts_only_a_quote_that_is_really_in_the_text() -> None:
    src = _files()["app/ai/documents_service.py"]
    mod = _parse_module(src)
    text = "page one\n\fvendor: Acme\ntotal: 12.50\n"
    start = text.index("12.50")
    good = {"value": "12.50", "confidence_bp": 9000, "start": start, "end": start + 5, "quote": "12.50"}
    assert mod.parse_field(good, text) == ("12.50", 9000, (2, start, start + 5, "12.50"))
    for bad in (
        {**good, "quote": "12.51"},
        {**good, "end": 9999},
        {**good, "start": start + 5},
        {**good, "start": True, "end": 5, "quote": "page "},
        {**good, "start": "3"},
        {k: v for k, v in good.items() if k != "quote"},
    ):
        assert mod.parse_field(bad, text) == ("12.50", 0, None), bad
    assert mod.parse_field({**good, "confidence_bp": 10001}, text)[1] == 0
    assert mod.parse_field({**good, "confidence_bp": 2.5}, text)[1] == 0
    assert mod.parse_field({**good, "confidence_bp": True}, text)[1] == 0
    assert mod.parse_field({"value": ""}, text) == (None, 0, None)
    assert mod.parse_field(None, text) == (None, 0, None)
    assert mod.parse_field({"value": 5}, text) == (None, 0, None)


def test_the_fake_provider_extracts_with_absolute_offsets() -> None:
    files = _files()
    providers = types.ModuleType("providers")
    exec(compile(files["app/ai/providers.py"], "providers", "exec"), providers.__dict__)  # noqa: S102
    text = ("x" * 50) + "\nvendor: Acme\ntotal = 9.99 [[conf=7000]]\ndue date: soon?\n"
    contents = [
        "EXTRACT FIELDS: vendor,total,due_date,missing\nrest",
        f"SEGMENT 0\n{text}",
        "SEGMENT 100\nignored: line\nvendor: Late\n",
    ]
    result = asyncio.run(providers.complete("fake", "fake-small", contents, 512, True, False, True))
    fields = json.loads(result.text)["fields"]
    assert set(fields) == {"vendor", "total", "due_date"}
    for name, value, conf in (("vendor", "Acme", 9500), ("total", "9.99", 7000), ("due_date", "soon?", 4000)):
        f = fields[name]
        assert f["value"] == f["quote"] == value and f["confidence_bp"] == conf and text[f["start"] : f["end"]] == value
    # a [[fake:json=...]] directive wins over extraction (a lying model in tests)
    forced = asyncio.run(providers.complete("fake", "fake-small", [*contents, '[[fake:json={"fields":{}}]]'], 512, True, False, True))
    assert json.loads(forced.text) == {"fields": {}}


def test_sentinel_fixes_in_the_generated_code() -> None:
    files = _files()
    providers = types.ModuleType("providers")
    exec(compile(files["app/ai/providers.py"], "providers", "exec"), providers.__dict__)  # noqa: S102
    assert "FAKE_DIRECTIVES = False" in files["app/ai/config.py"]  # M3: markers in text are ignored unless a test switches them on
    text = "total: 5 [[conf=100]] [[fake:fail]]\n"
    contents = ["EXTRACT FIELDS: total", f"SEGMENT 0\n{text}"]
    off = asyncio.run(providers.complete("fake", "fake-small", contents, 512, True, False))
    assert json.loads(off.text)["fields"]["total"]["confidence_bp"] == 9500  # not steered, no failure
    # M4: hostile markers parse in linear time (a bounded pattern)
    import time

    started = time.monotonic()
    asyncio.run(providers.complete("fake", "fake-small", ["[[fake:a=" * 20_000], 512, False, False, True))
    assert time.monotonic() - started < 3
    gateway = files["app/ai/service.py"]
    assert "hmac.new(" in gateway and "retain: bool = True" in gateway and "MAX_TOTAL_CHARS" in gateway  # L7, H1, M4
    schemas = files["app/ai/schemas.py"]
    call_out = schemas[schemas.index("class CallOut") : schemas.index("class UsageOut")]
    assert "prompt_text" not in call_out and "output_text" not in call_out and "prompt_hash" in call_out
    assert "retain=False" in files["app/ai/documents_service.py"] and "retain=False" in files["app/ai/knowledge_service.py"]
    assert "ALLOW_SELF_REVIEW = False" in files["app/ai/documents_config.py"]  # L2
    assert "max_length=2_000_000" in files["app/ai/documents_schemas.py"] and "max_length=5_000_000" in files["app/ai/knowledge_schemas.py"]  # L6


def test_zero_retention_and_documents_cannot_be_combined() -> None:
    raw = _raw()
    assert "zero_retention_conflict" not in _codes(raw)
    raw["packs"]["ai"]["gateway"]["zero_retention"] = True
    assert "zero_retention_conflict" in _codes(raw)
    del raw["packs"]["ai"]["documents"]
    assert "zero_retention_conflict" not in _codes(raw)  # knowledge alone is fine: its calls store no text either


def test_the_value_must_be_supported_by_its_quote() -> None:
    mod = _parse_module(_files()["app/ai/documents_service.py"])
    text = "total: $1,250.00 EUR\n"
    start = text.index("1,250.00")
    base = {"confidence_bp": 9000, "start": start, "end": start + 8, "quote": "1,250.00"}
    assert mod.parse_field({**base, "value": "1250.00"}, text)[1] == 9000
    assert mod.parse_field({**base, "value": "1 250.00"}, text)[1] == 9000
    for wrong in ("1250.001", "9999", "125", "1", "50", "1,250.00 and more"):
        v, conf, anchor = mod.parse_field({**base, "value": wrong}, text)
        assert (conf, anchor) == (0, None), wrong  # a fragment of a word of the quote is not support
    long = {**base, "start": 0, "end": len(text) - 1, "quote": text[:-1]}
    assert mod.parse_field({**long, "value": "1250.00"}, text)[1] == 9000  # a whole word of a longer quote is fine
