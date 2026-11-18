"""Audit B1-012: deploy.sh rollback/env/tag/prune/curl behaviour (run with fake docker+curl) and rls enable skipping."""

import os
import stat
import subprocess
from pathlib import Path

from app.core import rls

SCRIPT = Path(__file__).parents[2] / "deploy" / "prod" / "deploy.sh"

FAKE_DOCKER = r"""#!/bin/bash
echo "docker $*" >> "$LOG"
case "$1 $2" in
  "image ls") printf '%s\n' $IMAGES ;;
  "info --format") echo '{"runsc":{}}' ;;
esac
exit 0
"""
FAKE_CURL = '#!/bin/bash\necho "curl $*" >> "$LOG"\n[ "${CURL_FAIL:-0}" = 1 ] && exit 22\nexit 0\n'
FAKE_SLEEP = "#!/bin/bash\nexit 0\n"


def _setup(tmp: Path, env: str = "BB_DOMAIN=x.test\n", files: dict[str, str] | None = None) -> tuple[Path, dict[str, str]]:
    work = tmp / "srv"
    work.mkdir()
    (work / "deploy.sh").write_text(SCRIPT.read_text())
    (work / ".env").write_text(env)
    (work / "keys.txt").write_text("k1 x\n")
    for name, body in (files or {}).items():
        (work / name).write_text(body)
    bindir = tmp / "bin"
    bindir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL), ("sleep", FAKE_SLEEP)):
        f = bindir / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    log = tmp / "log"
    log.write_text("")
    environ = {"PATH": f"{bindir}:{os.environ['PATH']}", "LOG": str(log), "HOME": str(tmp)}
    return work, environ


def _run(work: Path, environ: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "deploy.sh", *args], cwd=work, env=environ, capture_output=True, text=True, timeout=60)


def test_rollback_flag_skips_migrate_but_keeps_db_role_and_rls(tmp_path: Path) -> None:
    work, env = _setup(tmp_path)
    env["BB_IMAGE_PREFIX"] = "ghcr.io/o"
    r = _run(work, env, "--no-migrate", "sha-a")
    assert r.returncode == 0, r.stderr
    log = Path(env["LOG"]).read_text()
    assert " migrate" not in log
    assert "run --rm db-role" in log and "rls enable --yes" in log
    r = _run(work, env, "sha-b")
    assert " migrate" in Path(env["LOG"]).read_text()


def test_missing_optional_keys_do_not_exit_silently_and_prefix_comes_from_env_file(tmp_path: Path) -> None:
    work, env = _setup(tmp_path, env='BB_DOMAIN="x.test"\r\nBB_IMAGE_PREFIX=ghcr.io/o\r\n')
    r = _run(work, env, "sha-a")  # no SANDBOX_ENABLED key, prefix not exported
    assert r.returncode == 0, r.stderr
    log = Path(env["LOG"]).read_text()
    assert "curl -fsS --connect-timeout 5 --max-time 10 https://x.test/health" in log


def test_redeploy_same_tag_keeps_rollback_target_and_current_written_after_health(tmp_path: Path) -> None:
    work, env = _setup(tmp_path, files={".current-tag": "sha-a", ".previous-tag": "none"})
    env["BB_IMAGE_PREFIX"] = "ghcr.io/o"
    env["CURL_FAIL"] = "1"
    r = _run(work, env, "sha-b")
    assert r.returncode == 1 and "--no-migrate sha-a" in r.stderr
    assert (work / ".current-tag").read_text().strip() == "sha-a"  # not advanced before health
    assert (work / ".previous-tag").read_text().strip() == "sha-a"
    _run(work, env, "sha-b")  # workflow re-run of the same bad tag
    assert (work / ".previous-tag").read_text().strip() == "sha-a"
    env["CURL_FAIL"] = "0"
    _run(work, env, "sha-b")
    assert (work / ".current-tag").read_text().strip() == "sha-b"
    _run(work, env, "sha-b")
    assert (work / ".previous-tag").read_text().strip() == "sha-a"


def test_old_sha_images_are_removed_current_and_previous_kept(tmp_path: Path) -> None:
    work, env = _setup(tmp_path, files={".current-tag": "sha-a"})
    env["BB_IMAGE_PREFIX"] = "ghcr.io/o"
    env["IMAGES"] = "ghcr.io/o/builder-api:sha-a ghcr.io/o/builder-api:sha-b ghcr.io/o/builder-api:sha-old ghcr.io/o/builder-api:latest other/x:sha-old"
    assert _run(work, env, "sha-b").returncode == 0
    removed = [ln for ln in Path(env["LOG"]).read_text().splitlines() if ln.startswith("docker image rm")]
    assert removed == ["docker image rm ghcr.io/o/builder-api:sha-old"]


def test_keys_hint_matches_deploy_doc(tmp_path: Path) -> None:
    work, env = _setup(tmp_path)
    (work / "keys.txt").unlink()
    env["BB_IMAGE_PREFIX"] = "ghcr.io/o"
    r = _run(work, env, "sha-a")
    assert r.returncode == 1 and "chown 10001" in r.stderr and "chmod 400" in r.stderr


def test_enable_statements_skip_tables_already_enabled_and_forced() -> None:
    tables = list(rls.ALL_TABLES)
    current = {t: {"enabled": True, "forced": True, "policy": True} for t in tables}
    assert rls.enable_statements(current) == []
    current[tables[0]]["forced"] = False
    stmts = rls.enable_statements(current)
    assert stmts == [f"ALTER TABLE {tables[0]} ENABLE ROW LEVEL SECURITY", f"ALTER TABLE {tables[0]} FORCE ROW LEVEL SECURITY"]
    assert len(rls.enable_statements()) == 2 * len(tables)
