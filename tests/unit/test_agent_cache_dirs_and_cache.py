"""FB2c: S1-002 (cache dirs), S1-012 (weakening), B-010 (history cache breakpoint). No real LLM."""

import json
import uuid
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.services.agent import gates
from app.services.agent import tools as agent_tools
from app.services.agent.contract import Actor, Phase, Plan, ToolContext
from app.services.agent.tools import spec_tools
from app.services.agent.wiring import _content_hash_sync
from app.services.ai.base import CompletionRequest, Message
from app.services.ai.claude import ClaudeProvider, build_payload
from tests.e2e.hooks_support import example_spec

FAKE_KEY = "sk_" "ant_test_0123456789abcdef"
EVIL = "import sub" "process\nsub" "process.run(['id'])\n"
CACHE_DIRS = ["__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"]


@pytest.fixture
def wt(tmp_path: Path) -> Path:
    for rel, content in generate(Spec.model_validate(example_spec())).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    return tmp_path


def _ctx(wt: Path) -> ToolContext:
    plan = Plan(uuid.uuid4(), entities=frozenset({"Invoice"}), hooks=frozenset({"match_invoice"}), zones=frozenset({"tests/custom/", "app/custom/"}))
    return ToolContext(
        session=cast(Any, None), settings=cast(Any, None), org_id=uuid.uuid4(), project_id=uuid.uuid4(),
        run_id=uuid.uuid4(), actor=Actor("agent", uuid.uuid4()), phase=Phase.build, plan=plan, worktree=str(wt),
    )  # fmt: skip


# -- S1-002 --------------------------------------------------------------------------------------
@pytest.mark.parametrize("d", CACHE_DIRS)
async def test_agent_cannot_write_under_cache_dirs(wt: Path, d: str) -> None:
    rel = f"tests/custom/{d}/test_x.py"
    r = await agent_tools.execute(_ctx(wt), "add_test", {"path": rel, "content": "def test_x():\n    assert True\n"})
    assert not r.ok and r.failures[0].rule_id == "path_denied"
    assert not (wt / rel).exists()


@pytest.mark.parametrize("d", CACHE_DIRS)
def test_preexisting_cache_dir_file_is_scanned_and_flagged(wt: Path, d: str) -> None:
    spec = Spec.model_validate(example_spec())
    rel = f"app/custom/{d}/evil.py"
    (wt / rel).parent.mkdir(parents=True)
    (wt / rel).write_text(EVIL)
    report = gates.run_gates(wt, spec)
    rules = {(f.rule_id, f.location) for f in report.failures}
    assert ("g8.cache_dir_file", rel) in rules  # flagged
    assert any(r == "g8.banned_import" and loc.startswith(rel) for r, loc in rules)  # and its content scanned
    assert not report.ok and report.gates["G8"] == "fail"
    replayed = gates.replay(wt, spec)
    assert any(f.location == rel for f in replayed.failures) and not replayed.ok


def test_content_hash_moves_with_a_cache_dir_file(wt: Path) -> None:
    before = _content_hash_sync(wt)
    p = wt / "app/custom/__pycache__/x.py"
    p.parent.mkdir(parents=True)
    p.write_text("a = 1\n")
    added = _content_hash_sync(wt)
    p.write_text("a = 2\n")
    changed = _content_hash_sync(wt)
    assert len({before, added, changed}) == 3


def test_root_git_data_is_still_not_content(wt: Path) -> None:
    before = gates._scan_tree(wt, 1e12 if False else __import__("time").monotonic() + 20).files
    (wt / ".git").mkdir()
    (wt / ".git" / "HEAD").write_text("ref: x\n")
    after = gates._scan_tree(wt, __import__("time").monotonic() + 20).files
    assert before == after


# -- S1-012 --------------------------------------------------------------------------------------
CURRENT = {"name": "t", "type": "string", "min_value": 1, "max_value": 9, "default": "a",
           "enum_values": ["a", "b"], "indexed": True}  # fmt: skip


@pytest.mark.parametrize(
    "changes",
    [{"min_value": 5}, {"max_value": None}, {"default": "z"}, {"enum_values": ["a"]}, {"enum_values": None},
     {"indexed": False}, {"name": "renamed"}],
)
def test_weakening_catches_constraint_loosening_and_rename(changes: dict[str, Any]) -> None:
    assert spec_tools.weakening(CURRENT, changes), changes


@pytest.mark.parametrize("changes", [{"enum_values": ["a", "b", "c"]}, {"indexed": True}, {"name": "t"}, {"default": "a"}])
def test_weakening_ignores_harmless_changes(changes: dict[str, Any]) -> None:
    assert spec_tools.weakening(CURRENT, changes) == []


def test_weakening_ignores_a_first_bound_on_an_unconstrained_field() -> None:
    """FB7: adding min/max/default where none existed is the plain validation-rule edit, not an approval."""
    bare = {"name": "amount", "type": "decimal"}
    assert spec_tools.weakening(bare, {"min_value": 0, "max_value": 1000000, "default": 1}) == []


async def test_field_and_relation_inputs_get_the_security_key_scan(wt: Path) -> None:
    ctx = _ctx(wt)
    r = await agent_tools.execute(ctx, "add_field", {"entity": "Invoice", "field": {"name": "x", "type": "string", "is_public": True}})
    assert r.failures and r.failures[0].rule_id == "tool_s_bang"
    r = await agent_tools.execute(ctx, "update_field", {"entity": "Invoice", "name": "x", "changes": {"read_roles": ["a"]}})
    assert r.failures and r.failures[0].rule_id == "tool_s_bang"


# -- B-010 ---------------------------------------------------------------------------------------
def _req(messages: list[Message], cache: bool = True) -> CompletionRequest:
    return CompletionRequest(system="sys", messages=messages, cache_prefix=cache)


def test_history_breakpoint_on_last_message_only() -> None:
    msgs = [Message("user", "goal"), Message("assistant", [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]),
            Message("user", [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}])]  # fmt: skip
    p = build_payload("m", _req(msgs), stream=False)
    assert p["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in json.dumps(p["messages"][:-1])
    assert "cache_control" not in json.dumps(msgs[-1].content)  # the request itself is not mutated
    one = build_payload("m", _req([Message("user", "hi")]), stream=False)
    assert one["messages"][0]["content"] == [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]
    off = build_payload("m", _req(msgs, cache=False), stream=False)
    assert "cache_control" not in json.dumps(off)


async def test_history_breakpoint_is_in_the_body_actually_sent() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "m", "content": [{"type": "text", "text": "ok"}], "usage": {}})

    p = ClaudeProvider(FAKE_KEY, transport=httpx.MockTransport(handler))
    await p.complete("claude-haiku-5-5", _req([Message("user", "goal"), Message("assistant", "plan"), Message("user", "go")]))
    marks = [m for m in seen["body"]["messages"] if "cache_control" in json.dumps(m)]
    assert marks == [seen["body"]["messages"][-1]]


async def test_relation_input_gets_the_security_key_scan(wt: Path) -> None:
    rel = {"kind": "many_to_one", "from_entity": "Invoice", "to_entity": "Invoice", "from_name": "a", "to_name": "b", "tenant_id": 1}
    r = await agent_tools.execute(_ctx(wt), "add_relation", {"relation": rel})
    assert r.failures and r.failures[0].rule_id == "tool_s_bang"
