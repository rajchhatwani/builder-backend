"""Audit B1-014: sandbox overlay exposure rules, runner health, Caddy admin off, deploy.sh sandbox preflight."""

import os
import re
import stat
from pathlib import Path
from typing import Any

import yaml

from tests.unit.test_audit_b1_012_deploy_script import _run, _setup

ROOT = Path(__file__).resolve().parents[2]


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!reset", lambda loader, node: None)


def _load(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / name).read_text(), Loader=_Loader)  # noqa: S506 - SafeLoader subclass


def test_caddy_admin_api_is_off() -> None:  # F-1160
    text = (ROOT / "docker/prod/Caddyfile").read_text()
    head = text.split("{$BB_DOMAIN}", 1)[0]
    assert re.search(r"^\s*admin off\s*$", head, re.M)


def test_overlay_ports_loopback_and_host_network_has_none() -> None:  # F-1161
    base, over = _load("docker-compose.prod.yml"), _load("docker-compose.sandbox.yml")
    for svc, conf in over["services"].items():
        for p in conf.get("ports") or []:
            assert str(p).startswith("127.0.0.1:"), (svc, p)
    merged_ports = {}
    for svc in set(base["services"]) | set(over["services"]):
        o = over["services"].get(svc, {})
        ports = o["ports"] if "ports" in o else base["services"].get(svc, {}).get("ports")
        merged_ports[svc] = ports or []
        host = o.get("network_mode") == "host" or (
            "network_mode" not in o and base["services"].get(svc, {}).get("network_mode") == "host"
        )
        if host:
            assert not merged_ports[svc], svc
        for p in merged_ports[svc]:
            assert str(p).startswith("127.0.0.1:") or svc == "web" and not host, (svc, p)


def test_runner_healthcheck_and_api_waits_for_healthy() -> None:  # F-1163
    over = _load("docker-compose.sandbox.yml")["services"]
    assert "healthcheck" in over["runner"]
    assert over["api"]["depends_on"]["runner"]["condition"] == "service_healthy"


def _sandbox_env(data: Path, token: str) -> str:
    return f"BB_DOMAIN=x.test\nSANDBOX_ENABLED=true\nBB_DATA={data}\nBB_RUNNER_TOKEN={token}\n"


def test_deploy_rejects_short_runner_token_before_pull(tmp_path: Path) -> None:  # F-1162
    work, env = _setup(tmp_path, env=_sandbox_env(tmp_path / "d", "abc"))
    env["BB_IMAGE_PREFIX"] = "ghcr.io/o"
    r = _run(work, env, "sha-a")
    assert r.returncode == 1 and "BB_RUNNER_TOKEN" in r.stderr
    assert " pull" not in Path(env["LOG"]).read_text()


def test_deploy_fails_clearly_when_data_dir_not_writable(tmp_path: Path) -> None:  # F-1159
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        work, env = _setup(tmp_path, env=_sandbox_env(ro / "d", "t" * 40))
        env["BB_IMAGE_PREFIX"] = "ghcr.io/o"
        r = _run(work, env, "sha-a")
    finally:
        ro.chmod(stat.S_IRWXU)
    assert r.returncode == 1 and "BB_DATA" in r.stderr and "install -d" in r.stderr


def test_deploy_fails_when_data_dir_not_owned_by_api_uid(tmp_path: Path) -> None:  # F-1159
    data = tmp_path / "d"
    (data / "previews").mkdir(parents=True)
    (data / "ws").mkdir()
    work, env = _setup(tmp_path, env=_sandbox_env(data, "t" * 40))
    env["BB_IMAGE_PREFIX"] = "ghcr.io/o"
    env["BB_API_UID"] = str(os.getuid() + 1)
    r = _run(work, env, "sha-a")
    assert r.returncode == 1 and "install -d" in r.stderr
    env["BB_API_UID"] = str(os.getuid())
    assert _run(work, env, "sha-a").returncode == 0
