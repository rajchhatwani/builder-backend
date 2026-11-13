"""CP-5D-AI: the AI pack, knowledge block (D35). Spec rules, emission only when declared, migration 0040, the permission
filter present in every read path of the generated service, and its pure parts executed (chunking, fake embedding, query
words). Retrieval against a real database (permissions, tenants, role change) is proven by
tests/e2e/test_ai_knowledge_stack.py."""

import ast
import json
import re
import types
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw() -> dict[str, Any]:
    return json.loads((FIXTURES / "ai_documents_knowledge.json").read_text(encoding="utf-8"))


def _files(raw: dict[str, Any] | None = None) -> dict[str, str]:
    return generate(Spec.model_validate(raw or _raw()))


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _service() -> types.ModuleType:
    """The pure helpers of the generated service, executed without the app around them."""
    tree = ast.parse(_files()["app/ai/knowledge_service.py"])
    keep = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.ClassDef | ast.Assign | ast.AnnAssign | ast.Import | ast.ImportFrom)
        and not (isinstance(n, ast.ImportFrom) and (n.module or "").startswith(("app.", "sqlalchemy")))
        and not (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("_SEARCH_SQL",) for t in n.targets))
        and not (isinstance(n, ast.FunctionDef) and n.name in ("_scoped", "_visibility", "_source_out"))
        and not (isinstance(n, ast.Import) and n.names[0].name.startswith("sqlalchemy"))
    ]
    module = types.ModuleType("knowledge_pure")
    exec(compile(ast.Module(body=keep, type_ignores=[]), "knowledge_pure", "exec"), module.__dict__)  # noqa: S102
    return module


def test_knowledge_is_emitted_with_its_config_and_migration() -> None:
    files = _files()
    config = files["app/ai/knowledge_config.py"]
    assert "CHUNK_CHARS = 200" in config and "STAGE = 'answer'" in config and "'admin', 'agent', 'customer'" in config
    assert "_ai_knowledge_router" in files["app/main.py"] and "knowledge_models" in files["app/models/__init__.py"]
    migration = files["alembic/versions/0040_ai_knowledge.py"]
    assert "Computed(" in migration and "postgresql_using=\"gin\"" in migration and "ck_ai_knowledge_sources_visibility" in migration


def test_every_read_path_applies_the_permission_filter_in_the_query() -> None:
    src = _files()["app/ai/knowledge_service.py"]
    assert "_VISIBLE_SQL" in src and "s.owner_id = :uid OR s.allowed_roles &&" in src
    # the filter is in the WHERE clause of the search, ahead of ORDER BY and LIMIT
    sql = re.search(r'_SEARCH_SQL = f"""(.*?)"""', src, re.S)
    assert sql is not None
    body = sql.group(1)
    assert body.index("{_VISIBLE_SQL}") < body.index("ORDER BY") < body.index("LIMIT")
    for fn in ("list_sources", "delete_source"):
        part = src[src.index(f"async def {fn}") :].split("\nasync def ")[0]
        assert "_visibility(user)" in part, fn
    ask = src[src.index("async def ask") :]
    assert "hits = await search(" in ask and ask.index("if not hits") < ask.index("_gateway.complete")  # no hit: no model call
    # roles come from the current user row, never from a cached claim
    assert "effective_roles(user.roles)" in src


def test_validation_rules() -> None:
    def with_kn(**patch: Any) -> set[str]:
        raw = _raw()
        raw["packs"]["ai"]["knowledge"].update(patch)
        return _codes(raw)

    assert "unknown_stage" in with_kn(stage="nope")
    assert "unknown_role" in with_kn(manage_roles=["wizard"], read_roles=["wizard"])
    assert "empty" in with_kn(manage_roles=[])
    assert "out_of_range" in with_kn(chunk_chars=99)
    assert "out_of_range" in with_kn(chunk_chars=5001)
    assert "out_of_range" in with_kn(max_sources=0)
    assert "out_of_range" in with_kn(max_text_chars=5_000_001)
    raw = _raw()
    del raw["packs"]["ai"]["gateway"]
    assert "needs_gateway" in _codes(raw)


def test_chunking_respects_the_size_and_loses_nothing() -> None:
    mod = _service()
    text = " ".join(f"word{i}" for i in range(300))
    chunks = mod.chunk_text(text, 200)
    assert len(chunks) > 3 and all(0 < len(c) <= 200 for c in chunks)
    assert " ".join(chunks).split() == text.split()
    assert mod.chunk_text("short", 200) == ["short"] and mod.chunk_text("   \n  ", 200) == []
    assert mod.chunk_text("x" * 450, 200) == ["x" * 200, "x" * 200, "x" * 50]
    assert mod.chunk_text(text, 200) == chunks  # deterministic


def test_the_fake_embedding_is_deterministic_and_words_drop_stop_words() -> None:
    mod = _service()
    a, b = mod.EMBEDDER.embed("Refund the policy"), mod.EMBEDDER.embed("policy refund")
    assert a == b and len(a) == 128 and sum(a) == 2 and all(isinstance(v, int) for v in a)
    assert mod._words("What is the ZEBRA-7731 refund?") == ["zebra", "7731", "refund"]
    assert mod.EMBEDDER.embed("the of is") == [0] * 128
