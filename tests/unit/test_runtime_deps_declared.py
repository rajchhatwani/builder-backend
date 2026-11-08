"""S2-003: every third-party package imported under app/ is a runtime dependency.

The Docker image installs `uv sync --no-dev`; a package that sits only in the dev group imports
fine in the test venv and crashes the container.
"""

import ast
import importlib.metadata as md
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Import names with no installed distribution to map (none today). Keep it empty if possible.
ALLOWED_UNMAPPED: frozenset[str] = frozenset()


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> set[str]:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    return {_norm(re.split(r"[\[<>=!~; ]", d, maxsplit=1)[0]) for d in deps}


def _third_party_imports() -> dict[str, str]:
    """top-level import name -> one file that imports it."""
    found: dict[str, str] = {}
    for path in sorted((ROOT / "app").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for full in names:
                top = full.split(".")[0]
                if top not in sys.stdlib_module_names and top != "app":
                    found.setdefault(top, str(path.relative_to(ROOT)))
    return found


def test_every_third_party_import_is_a_runtime_dependency() -> None:
    declared = _declared()
    owners = md.packages_distributions()
    missing = []
    for top, where in _third_party_imports().items():
        if top in ALLOWED_UNMAPPED:
            continue
        dists = {_norm(d) for d in owners.get(top, [])}
        if not dists:
            missing.append(f"{top} ({where}): not installed, cannot map to a distribution")
        elif not dists & declared:
            missing.append(f"{top} ({where}): {sorted(dists)} not in [project].dependencies")
    assert not missing, "declare these in [project].dependencies:\n" + "\n".join(missing)


def test_runtime_only_via_framework_packages_are_declared() -> None:
    # Imported by name nowhere, but required at runtime (FastAPI Form/UploadFile needs it).
    assert "python-multipart" in _declared()
