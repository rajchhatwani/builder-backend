"""WP-B (Cycle 4): agent hardening from the first real run. Unit level, no database, no network,
no real model: authoring guide, gate cache, G10-G12, promotion persistence helpers, cache cleaning,
the X tools over a fake sandbox, and the local adapters of the E tools."""

import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core import naming
from app.core.generator import generate
from app.core.spec_models import Spec
from app.exceptions import AppError
from app.services.agent import approved_effects, external_adapters, gates, gates_extra, promote
from app.services.agent import tools as agent_tools
from app.services.agent.cache_clean import clean_caches
from app.services.agent.contract import Actor, Phase, Plan, ToolContext
from app.services.agent.tools import exec_tools, read_tools
from app.services.ops.registry import section_adapter
from app.services.sandbox.base import RunResult, SandboxError
from tests.e2e.hooks_support import example_spec


def ctx_for(worktree: Path | None = None, **kw: Any) -> ToolContext:
    return ToolContext(
        session=cast(Any, kw.pop("session", None)),
        settings=cast(Any, kw.pop("settings", SimpleNamespace(
            preview_app_image="img:1", agent_gate_licence=True, agent_gate_static_analysis=True,
            agent_gate_strict_typing=False))),
        org_id=uuid.uuid4(), project_id=uuid.uuid4(), run_id=kw.pop("run_id", uuid.uuid4()),
        actor=Actor("agent", uuid.uuid4()), phase=kw.pop("phase", Phase.build), plan=Plan(uuid.uuid4()),
        worktree=str(worktree) if worktree else None, **kw,
    )


# -- FX-9: authoring guide ---------------------------------------------------------------------


async def test_authoring_guide_is_a_plan_phase_read_tool_with_valid_examples() -> None:
    assert "get_authoring_guide" in {t.name for t in agent_tools.tools_for(Phase.plan)}
    r = await agent_tools.execute(ctx_for(phase=Phase.plan), "get_authoring_guide", {})
    assert r.ok
    g = r.data
    assert naming.SNAKE_NAME_RE.pattern in g["entity"]["plural_path"]  # the pattern comes from the validator
    assert "transition_guard" in g["hook"]["point_pattern"]
    sm = g["state_machine"]["example"]
    assert section_adapter("state_machines").validate_python([sm])  # the example is a valid item
    assert section_adapter("hooks").validate_python([g["hook"]["example"]])
    assert {"from_states", "to_state"} <= set(sm["transitions"][0])
    assert "EVERYTHING" in g["plan_ahead"]


# -- FX-9: gate report reuse ---------------------------------------------------------------------


async def test_read_gate_report_is_reused_until_the_tree_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = Spec.model_validate(example_spec())
    root = tmp_path / "wt"
    root.mkdir()
    (root / "a.txt").write_text("1")
    calls = {"run": 0}
    real = gates.run_gates

    def counting(*a: Any, **k: Any) -> Any:
        calls["run"] += 1
        return real(*a, **k)

    async def fake_spec(*_a: Any, **_k: Any) -> Spec:
        return spec

    class NoPins:
        def __init__(self, _s: Any) -> None: ...

        async def approved_pins(self, _p: Any) -> list[Any]:
            return []

    monkeypatch.setattr(gates, "run_gates", counting)
    monkeypatch.setattr(read_tools, "run_spec", fake_spec)
    monkeypatch.setattr("app.services.dependency_policy_service.DependencyPolicyService", NoPins)
    monkeypatch.setattr(gates, "replay", lambda *a, **k: gates.GateReport(True, [], {}))
    ctx = ctx_for(root, session=object())
    first = await read_tools.last_gate_report(ctx)
    second = await read_tools.last_gate_report(ctx)
    assert calls["run"] == 1 and second["cached"] is True and "cached" not in first
    assert second["report_hash"] == first["report_hash"]
    (root / "a.txt").write_text("22")  # the tree changed: recomputed
    third = await read_tools.last_gate_report(ctx)
    assert calls["run"] == 2 and "cached" not in third
    (root / "b.txt").write_text("x")  # a new file also invalidates
    await read_tools.last_gate_report(ctx)
    assert calls["run"] == 3
    other = await read_tools.last_gate_report(ctx_for(root, session=object()))  # another run: its own entry
    assert calls["run"] == 4 and "cached" not in other


# -- FX-6: G10 licence ------------------------------------------------------------------------


def test_denied_licence_matches_copyleft_not_lgpl() -> None:
    for text in ("GPL-3.0-or-later", "GNU Affero General Public License (AGPL)", "SSPL-1.0", "BUSL-1.1"):
        assert gates_extra.denied_licence(text), text
    for text in ("MIT", "Apache-2.0", "LGPL-3.0-only", "GNU Lesser General Public License v3 (LGPLv3)", "BSD-3-Clause"):
        assert not gates_extra.denied_licence(text), text


def test_licence_gate_fails_on_copyleft_and_never_assumes_unknown_is_fine() -> None:
    reqs = {"requirements-extra.txt": "alpha==1.0\nbeta==2.0\n"}
    bad = gates_extra.licence_gate(reqs, lookup=lambda n: "GPL-3.0" if n == "alpha" else "MIT")
    assert bad.gates["G10"] == "fail" and bad.failures[0].rule_id == "g10.licence"
    assert "alpha" in bad.failures[0].actual
    ok = gates_extra.licence_gate(reqs, lookup=lambda n: "MIT")
    assert ok.gates["G10"] == "pass" and not ok.failures
    none_known = gates_extra.licence_gate(reqs, lookup=lambda n: None)
    assert none_known.gates["G10"] == "skipped" and "alpha" in none_known.skipped["G10"]
    some = gates_extra.licence_gate(reqs, lookup=lambda n: "MIT" if n == "alpha" else None)
    assert some.gates["G10"] == "pass" and "beta" in some.skipped["G10"]  # partly unchecked is said out loud
    empty = gates_extra.licence_gate({})
    assert empty.gates["G10"] == "skipped" and empty.skipped["G10"]


# -- FX-6: G11 static analysis (only when a tool is installed locally) -----------------------------


def test_static_gate_without_a_tool_is_skipped_with_the_reason(tmp_path: Path) -> None:
    res = gates_extra.static_gate(tmp_path, ["app/custom/x.py"], which=lambda _t: None)
    assert res.gates["G11"] == "skipped" and "installed locally" in res.skipped["G11"] and not res.failures


def test_static_gate_with_bandit_reports_high_findings_and_never_installs(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def runner(argv: list[str], cwd: Path) -> tuple[int, str]:
        seen.append(argv)
        return 1, '{"results": [{"filename": "app/custom/x.py", "test_id": "B602", "line_number": 3, "issue_text": "shell"}]}'

    res = gates_extra.static_gate(tmp_path, ["app/custom/x.py", "app/other.py", "README.md"],
                                  which=lambda t: "/usr/bin/bandit" if t == "bandit" else None, runner=runner)
    assert res.gates["G11"] == "fail" and res.failures[0].rule_id == "g11.bandit" and "B602" in res.failures[0].actual
    assert seen[0][0] == "bandit" and "app/custom/x.py" in seen[0] and "app/other.py" not in seen[0]
    assert not any(w in " ".join(seen[0]) for w in ("pip", "install", "http"))
    clean = gates_extra.static_gate(tmp_path, ["app/custom/x.py"], which=lambda t: "/b" if t == "bandit" else None,
                                    runner=lambda a, c: (0, '{"results": []}'))
    assert clean.gates["G11"] == "pass"


def test_static_gate_unreadable_output_is_skipped_not_green(tmp_path: Path) -> None:
    res = gates_extra.static_gate(tmp_path, ["app/custom/x.py"], which=lambda t: "/b" if t == "bandit" else None,
                                  runner=lambda a, c: (2, "garbage"))
    assert res.gates["G11"] == "skipped" and res.skipped["G11"]

    def boom(argv: list[str], cwd: Path) -> tuple[int, str]:
        raise subprocess.TimeoutExpired("bandit", 1)

    res2 = gates_extra.static_gate(tmp_path, ["app/custom/x.py"], which=lambda t: "/b" if t == "bandit" else None, runner=boom)
    assert res2.gates["G11"] == "skipped"


def test_static_gate_never_uses_semgrep(tmp_path: Path) -> None:
    res = gates_extra.static_gate(tmp_path, ["app/hooks/y.py"], which=lambda t: "/s" if t == "semgrep" else None, runner=lambda *a: (0, ""))
    assert res.gates.get(gates_extra.STATIC) == "skipped" and res.skipped


def test_typing_gate_is_opt_in_and_checks_annotations(tmp_path: Path) -> None:
    (tmp_path / "app/custom").mkdir(parents=True)
    (tmp_path / "app/custom/a.py").write_text("def f(x, y: int):\n    return x\n\nclass C:\n    def m(self) -> int:\n        return 1\n")
    off = gates_extra.typing_gate(tmp_path, ["app/custom/a.py"], enabled=False)
    assert off.gates["G12"] == "skipped" and "not enabled" in off.skipped["G12"]
    on = gates_extra.typing_gate(tmp_path, ["app/custom/a.py"], enabled=True)
    assert on.gates["G12"] == "fail" and [f.rule_id for f in on.failures] == ["g12.untyped_def"]
    assert on.failures[0].location == "app/custom/a.py:1" and "x" in on.failures[0].actual
    (tmp_path / "app/custom/a.py").write_text("def f(x: int, y: int) -> int:\n    return x + y\n")
    assert gates_extra.typing_gate(tmp_path, ["app/custom/a.py"], enabled=True).gates["G12"] == "pass"


def test_run_gates_reports_g10_to_g12_and_skip_reasons(tmp_path: Path) -> None:
    spec = Spec.model_validate(example_spec())
    for rel, content in generate(spec).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (tmp_path / "app/custom_routers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app/custom_routers/z.py").write_text("def untyped(a):\n    return a\n")
    r = gates.run_gates(tmp_path, spec, strict_typing=True)
    assert {"G10", "G11", "G12"} <= set(r.gates)
    assert r.gates["G12"] == "fail" and any(f.rule_id == "g12.untyped_def" for f in r.failures)
    assert r.gates["G10"] == "skipped" and r.skipped["G10"]  # no hand-written requirements: said, not green
    off = gates.run_gates(tmp_path, spec)
    assert off.gates["G12"] == "skipped" and "G12" in off.skipped
    assert gates.report_hash(r) != gates.report_hash(off)  # the new gates are part of the report hash
    rp = gates.replay(tmp_path, spec, strict_typing=True)
    assert rp.gates["G12"] == "fail"


# -- FX-3: promotion persistence helpers -------------------------------------------------------------


def test_promotion_encode_decode_round_trip_and_rejects_tampering() -> None:
    files = {"app/custom/hooks/h.py": b"x = 1\n", "tests/custom/test_h.py": b"def test_a():\n    pass\n"}
    doc = promote.encode(files)
    assert doc is not None and doc["state"] == "pending" and doc["attempts"] == 0
    assert promote.decode(doc) == files
    assert promote.encode({}) is None
    assert promote.decode({**doc, "state": "done"}) is None
    assert promote.decode({**doc, "files": {"app/main.py": "eA=="}}) is None  # not a custom-zone path
    assert promote.decode({**doc, "files": {"app/custom/hooks/h.py": "!!notb64"}}) is None
    assert promote.decode(None) is None


def test_deleted_or_missing_custom_files_are_never_promoted(tmp_path: Path) -> None:
    (tmp_path / "app/custom/hooks").mkdir(parents=True)
    (tmp_path / "app/custom/hooks/keep.py").write_text("a = 1\n")
    hashes = promote.custom_file_hashes(tmp_path, ["app/custom/hooks/keep.py", "app/custom/hooks/gone.py"])
    assert list(hashes) == ["app/custom/hooks/keep.py"]  # the deleted file is not in the approved list
    with pytest.raises(AppError) as exc:  # a file that vanished after the review refuses the promotion
        promote.collect(tmp_path, {**hashes, "app/custom/hooks/gone.py": "0" * 64})
    assert exc.value.code == "promotion_hash_mismatch"


def test_promotion_total_size_is_capped(tmp_path: Path) -> None:
    (tmp_path / "app/custom").mkdir(parents=True)
    declared = {}
    for i in range(5):
        data = b"#" * (promote.MAX_PROMOTED_BYTES - 10)
        (tmp_path / f"app/custom/f{i}.py").write_bytes(data)
        declared[f"app/custom/f{i}.py"] = promote._sha(data)
    with pytest.raises(AppError) as exc:
        promote.collect(tmp_path, declared)
    assert exc.value.code == "promotion_refused"


# -- FX-5: cache cleaning and the X tools ----------------------------------------------------------


def test_clean_caches_removes_cache_folders_but_not_git_or_links(tmp_path: Path) -> None:
    (tmp_path / "app/custom/__pycache__").mkdir(parents=True)
    (tmp_path / "app/custom/__pycache__/a.pyc").write_bytes(b"x")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".git/objects").mkdir(parents=True)
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}"
    (outside / "__pycache__").mkdir(parents=True)
    (tmp_path / "link").symlink_to(outside)
    assert clean_caches(tmp_path) == 2
    assert not (tmp_path / "app/custom/__pycache__").exists() and not (tmp_path / ".pytest_cache").exists()
    assert (tmp_path / ".git/objects").is_dir() and (outside / "__pycache__").is_dir()  # links not followed


class FakeBox:
    def __init__(self, result: RunResult | Exception) -> None:
        self.result, self.specs = result, []  # type: ignore[var-annotated]

    async def run(self, spec: Any) -> RunResult:
        self.specs.append(spec)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _use_box(monkeypatch: pytest.MonkeyPatch, box: FakeBox) -> None:
    from app.services import preview_service

    monkeypatch.setattr(preview_service, "get_sandbox", lambda _s=None: box)


async def test_run_tests_cleans_caches_first_and_runs_only_in_the_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests/custom").mkdir(parents=True)
    (tmp_path / "tests/custom/test_a.py").write_text("def test_a():\n    assert True\n")
    (tmp_path / "tests/custom/__pycache__").mkdir()
    box = FakeBox(RunResult("s", 0, "1 passed\n", "", duration_seconds=0.5))
    _use_box(monkeypatch, box)
    seen_cache: list[bool] = []
    real_run = box.run

    async def spy(spec: Any) -> RunResult:
        seen_cache.append((tmp_path / "tests/custom/__pycache__").exists())
        return await real_run(spec)

    box.run = spy  # type: ignore[method-assign]
    r = await agent_tools.execute(ctx_for(tmp_path), "run_tests", {})
    assert r.ok and r.data["status"] == "passed" and seen_cache == [False]  # cleaned BEFORE the run (G8)
    spec = box.specs[0]
    assert spec.code_dir == tmp_path.resolve() and spec.image == "img:1" and spec.env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "untrusted_text" in r.data["output"]


async def test_run_tests_failure_timeout_missing_dir_and_sandbox_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r0 = await agent_tools.execute(ctx_for(tmp_path), "run_tests", {})
    assert r0.ok and r0.data["status"] == "no_tests"
    (tmp_path / "tests/custom").mkdir(parents=True)
    _use_box(monkeypatch, FakeBox(RunResult("s", 1, "F\n1 failed", "")))
    r1 = await agent_tools.execute(ctx_for(tmp_path), "run_tests", {})
    assert not r1.ok and r1.failures[0].rule_id == "tests.failed" and r1.data["status"] == "failed"
    _use_box(monkeypatch, FakeBox(RunResult("s", None, "", "", timed_out=True)))
    assert (await agent_tools.execute(ctx_for(tmp_path), "run_tests", {})).data["status"] == "timed_out"
    _use_box(monkeypatch, FakeBox(SandboxError("no runtime")))
    r3 = await agent_tools.execute(ctx_for(tmp_path), "run_tests", {})
    assert not r3.ok and r3.failures[0].rule_id == "sandbox_unavailable"


async def test_preview_tools_refuse_without_a_workspace_or_a_preview() -> None:
    r = await agent_tools.execute(ctx_for(), "start_preview", {})
    assert r.failures[0].rule_id == "no_worktree"
    r2 = await agent_tools.execute(ctx_for(), "call_endpoint", {"method": "GET", "path": "/x"})
    assert r2.failures[0].rule_id == "no_preview" and "start_preview" in r2.failures[0].hint
    for bad in ("x", "//evil", "/a b", "/a#b"):
        r3 = await agent_tools.execute(ctx_for(), "call_endpoint", {"method": "GET", "path": bad})
        assert r3.failures[0].rule_id == "path_invalid", bad


async def test_exec_tools_stay_inside_the_sandbox_and_preview_runtime() -> None:
    src = Path(exec_tools.__file__).read_text()
    assert "subprocess" not in src and "os.system" not in src and "create_subprocess" not in src
    assert "get_sandbox" in src and "PreviewService" in src and "verify_upstream" in src


# -- FX-4: E tool executors (local adapters, no outbound) --------------------------------------------


def _approval(action: str, **payload: Any) -> Any:
    return SimpleNamespace(kind="E", payload={"action": action, **payload})


async def test_request_secret_executor_records_the_name_never_a_value() -> None:
    run = SimpleNamespace(id=uuid.uuid4())
    out = await approved_effects.execute(cast(Any, None), cast(Any, run), _approval("request_secret", name="STRIPE_API_KEY"))
    assert out["executed"] is True and out["status"] == "awaiting_value" and out["outbound"] is False
    bad = await approved_effects.execute(cast(Any, None), cast(Any, run), _approval("request_secret", name="sk_" "live_abc"))
    assert bad["executed"] is False and bad["error"] == "secret_name_invalid"


async def test_create_pr_executor_records_a_local_pull_request(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "i"], check=True)  # fmt: skip

    class Sess:
        async def get(self, _model: Any, _id: Any) -> Any:
            return SimpleNamespace(worktree_path=str(tmp_path), branch="draft/abc")

    run = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4())
    out = await approved_effects.execute(cast(Any, Sess()), cast(Any, run), _approval("create_pr", title="Add invoices"))
    pr = out["pull_request"]
    assert out["executed"] is True and out["pushed"] is False and out["outbound"] is False
    assert pr["branch"] == "draft/abc" and len(pr["head"]) == 40 and pr["title"] == "Add invoices"
    nows = SimpleNamespace(id=uuid.uuid4(), workspace_id=None)
    refused = await approved_effects.execute(cast(Any, Sess()), cast(Any, nows), _approval("create_pr", title="x"))
    assert refused["executed"] is False and refused["error"] == "approval_not_applicable"


async def test_apply_migration_executor_plans_the_change_and_refuses_destructive_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    base = example_spec()
    draft = Spec.model_validate(base).model_copy(deep=True)
    draft.entities[0].fields.append(type(draft.entities[0].fields[0])(name="note", type="string"))
    holder: dict[str, Spec] = {"draft": draft}

    async def fake_spec(*_a: Any, **_k: Any) -> Spec:
        return holder["draft"]

    monkeypatch.setattr(external_adapters, "run_spec", fake_spec)
    run = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), plan={"base_spec": base})
    out = await approved_effects.execute(cast(Any, None), cast(Any, run), _approval("apply_migration", env="dev"))
    assert out["executed"] is True and out["applied_to_database"] is False and out["steps"] >= 1 and out["outbound"] is False
    destructive = Spec.model_validate(base).model_copy(deep=True)
    destructive.entities = destructive.entities[1:] or []
    holder["draft"] = destructive
    no = await approved_effects.execute(cast(Any, None), cast(Any, run), _approval("apply_migration", env="dev"))
    assert no["executed"] is False and no["error"] in ("migration_destructive", "migration_plan_failed")
    nobase = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), plan=None)
    assert (await approved_effects.execute(cast(Any, None), cast(Any, nobase), _approval("apply_migration", env="dev")))["executed"] is False


async def test_adapters_can_be_replaced_for_a_real_integration() -> None:
    class Pr:
        async def create(self, session: Any, run: Any, title: str) -> dict[str, Any]:
            return {"adapter": "fake-host", "outbound": False, "pull_request": {"id": "42", "title": title}}

    before = external_adapters.get_adapters()
    try:
        external_adapters.set_adapters(external_adapters.Adapters(before.dev, Pr(), before.secrets))
        out = await approved_effects.execute(cast(Any, None), cast(Any, SimpleNamespace(id=uuid.uuid4())), _approval("create_pr", title="T"))
        assert out["adapter"] == "fake-host" and out["pull_request"]["id"] == "42"
    finally:
        external_adapters.set_adapters(None)
    assert isinstance(external_adapters.get_adapters().pull_requests, external_adapters.LocalPullRequests)


