"""Audit B1-002: app/ must only import runtime deps (the prod image syncs with --no-dev)."""

import ast
import re
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def _dist_name(spec: str) -> str:
    m = re.match(r"[A-Za-z0-9_.-]+", spec)
    assert m
    return m.group(0).lower().replace("_", "-").replace(".", "-")


def _dev_only_modules() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = {_dist_name(s) for s in data["project"]["dependencies"]}
    dev = {_dist_name(s) for s in data["dependency-groups"]["dev"]} - runtime
    mods: set[str] = set()
    for mod, dists in packages_distributions().items():
        if any(d.lower().replace("_", "-").replace(".", "-") in dev for d in dists) and not any(
            d.lower().replace("_", "-").replace(".", "-") in runtime for d in dists
        ):
            mods.add(mod)
    return mods


def _imported_top_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_dev_only_module_set_is_detected() -> None:
    mods = _dev_only_modules()
    assert {"boto3", "redis", "opentelemetry", "testcontainers", "pytest"} <= mods


def test_app_does_not_import_dev_only_packages() -> None:
    dev_only = _dev_only_modules()
    bad = {
        str(p.relative_to(ROOT)): sorted(mods & dev_only)
        for p in (ROOT / "app").rglob("*.py")
        if (mods := _imported_top_modules(p)) & dev_only
    }
    assert not bad, f"imports of dev-group-only packages in app/: {bad}"
