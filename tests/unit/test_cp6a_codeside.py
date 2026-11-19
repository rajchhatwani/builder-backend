"""CP-6A CO6-4 (code-side go-live checks) and the deploy.sh keys.txt hint."""

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _helper():
    spec = importlib.util.spec_from_file_location("golive_docker_pools", ROOT / "scripts" / "golive_docker_pools.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _daemon(tmp_path, cfg):
    p = tmp_path / "daemon.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return str(p)


def test_no_pools_key_warns_that_docker_may_use_the_sandbox_range(tmp_path):
    level, detail = _helper().check(_daemon(tmp_path, {"runtimes": {}}), "172.30.0.0/16")
    assert level == "WARN" and "172.30.0.0/16" in detail


def test_missing_daemon_json_counts_as_no_pools(tmp_path):
    level, _ = _helper().check(str(tmp_path / "nope.json"), "172.30.0.0/16")
    assert level == "WARN"


def test_pool_outside_docker_builtin_ranges_is_ok_without_config(tmp_path):
    level, _ = _helper().check(_daemon(tmp_path, {}), "10.99.0.0/16")
    assert level == "OK"


def test_overlapping_default_pool_fails(tmp_path):
    cfg = {"default-address-pools": [{"base": "172.30.0.0/12", "size": 24}]}
    level, detail = _helper().check(_daemon(tmp_path, cfg), "172.30.0.0/16")
    assert level == "FAIL" and "overlaps" in detail


def test_disjoint_default_pool_is_ok(tmp_path):
    cfg = {"default-address-pools": [{"base": "10.200.0.0/16", "size": 24}]}
    level, _ = _helper().check(_daemon(tmp_path, cfg), "172.30.0.0/16")
    assert level == "OK"


def test_unreadable_json_warns_not_fails(tmp_path):
    bad = tmp_path / "daemon.json"
    bad.write_text("{not json", encoding="utf-8")
    level, _ = _helper().check(str(bad), "172.30.0.0/16")
    assert level == "WARN"


def test_cli_exit_codes(tmp_path):
    ok = _daemon(tmp_path, {"default-address-pools": [{"base": "10.200.0.0/16", "size": 24}]})
    script = str(ROOT / "scripts" / "golive_docker_pools.py")
    good = subprocess.run(["python3", "-I", script, ok, "172.30.0.0/16"], capture_output=True, text=True)
    assert good.returncode == 0 and good.stdout.startswith("OK")
    bad_cfg = _daemon(tmp_path, {"default-address-pools": [{"base": "172.30.0.0/16", "size": 24}]})
    bad = subprocess.run(["python3", "-I", script, bad_cfg, "172.30.0.0/16"], capture_output=True, text=True)
    assert bad.returncode == 1 and bad.stdout.startswith("FAIL")


def test_golive_check_runs_the_pool_and_image_checks_and_parses():
    text = (ROOT / "scripts" / "golive_check.sh").read_text(encoding="utf-8")
    assert "golive_docker_pools.py" in text and "P7 docker address pools" in text
    assert "P8 preview image" in text and "price table is UNVERIFIED" in text
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "golive_check.sh")]).returncode == 0


def test_deploy_sh_keys_hint_says_chown_then_chmod_400():
    line = next(
        ln for ln in (ROOT / "deploy" / "prod" / "deploy.sh").read_text(encoding="utf-8").splitlines()
        if "keys.txt missing" in ln
    )
    assert "chown 10001" in line and "chmod 400" in line and "chmod 600" not in line
