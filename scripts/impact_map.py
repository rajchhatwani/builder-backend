#!/usr/bin/env python3
"""Blast-radius mapper (stdlib only). Decides WHICH checks a change needs, before anything is committed.

Reads the git working tree (or --staged / --base REF), builds the import graph of app/ and tests/
(AST imports + "app.x.y" strings such as mock.patch targets), and writes into --out:
  report.txt            human report: changed files, blast radius, why each test was picked, what is skipped
  ruff.txt mypy.flag unit.txt api.txt slow.txt          python work lists (one path/node id per line)
  vitest.txt specs.txt tsc.flag                          frontend work lists
Nothing here runs a test and nothing writes outside --out.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git", ".mypy_cache", ".ruff_cache"}

# path regex -> (extra test globs, why). Globs are relative to repo root; missing matches are ignored.
ZONES: list[tuple[str, list[str], str]] = [
    (
        r"^app/(api/mcp|services/mcp)|^app/core/platform_authz\.py",
        [
            "tests/api/test_mcp*.py",
            "tests/api/test_plan_allow_mcp.py",
            "tests/unit/test_mcp*.py",
            "tests/api/test_*token*.py",
            "tests/api/test_*scope*.py",
        ],
        "MCP zone: tools, scopes, host allow-list, token pages",
    ),
    (
        r"^app/api/",
        ["tests/unit/test_openapi_snapshot.py"],
        "API surface changed: OpenAPI snapshot",
    ),
    (
        r"^app/(models|db)/|migrations/|alembic",
        ["tests/api/test_migrations.py"],
        "schema/migration zone",
    ),
    (
        r"^app/core/generator/",
        ["tests/unit/test_lifecycle_generated.py", "tests/unit/test_*generat*.py"],
        "generator zone: generated-code unit tests (generated-project e2e only with --slow)",
    ),
]
# cheap structural guards, run whenever any app/*.py changed
GUARDS_APP = ["tests/unit/test_zones.py", "tests/unit/test_module_manifest.py"]
GUARD_NEW_TEST = ["tests/unit/test_manifest_coverage.py"]
SHARED_FRONTEND = re.compile(
    r"(index\.css|/components/(Layout|Sidebar|Shell)|ProjectWorkspace|AdminApp)"
)
STR_REF = re.compile(r"\b(?:app|tests)(?:\.\w+)+")


def git(*a: str) -> list[str]:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True)
    return [x for x in r.stdout.split("\n") if x]


def changed_files(base: str | None, staged: bool) -> list[str]:
    if base:
        names = git("diff", "--name-only", base)
    elif staged:
        names = git("diff", "--name-only", "--cached")
    else:
        names = git("diff", "--name-only", "HEAD")
    if not staged:
        names += git("ls-files", "--others", "--exclude-standard")
    return sorted(set(names))


def added_files(base: str | None, staged: bool) -> set[str]:
    out = set(git("ls-files", "--others", "--exclude-standard")) if not staged else set()
    ref = ["--cached"] if staged and not base else [base or "HEAD"]
    out |= set(git("diff", "--name-only", "--diff-filter=A", *ref))
    return out


def py_files() -> list[Path]:
    res = []
    for d in ("app", "tests"):
        for p in (ROOT / d).rglob("*.py"):
            rel = p.relative_to(ROOT).parts
            # tests/golden + tests/fixtures hold generated-project files (pytest norecursedirs)
            if not (set(p.parts) & SKIP_DIRS) and rel[:2] not in (
                ("tests", "golden"),
                ("tests", "fixtures"),
            ):
                res.append(p)
    return res


def mod_of(p: Path) -> str:
    parts = list(p.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def longest_known(name: str, known: set[str]) -> str | None:
    parts = name.split(".")
    while parts:
        c = ".".join(parts)
        if c in known:
            return c
        parts.pop()
    return None


def refs_of(path: Path, mod: str, known: set[str]) -> set[str]:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    is_pkg = path.name == "__init__.py"
    out: set[str] = set()

    def add(n: str) -> None:
        k = longest_known(n, known)
        if k and k != mod:
            out.add(k)

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                add(a.name)
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = mod if is_pkg else (mod.rsplit(".", 1)[0] if "." in mod else "")
                parts = pkg.split(".") if pkg else []
                parts = parts[: len(parts) - (n.level - 1)]
                base = ".".join(parts + ([n.module] if n.module else []))
            if base:
                add(base)
            for a in n.names:
                cand = f"{base}.{a.name}" if base else a.name
                if cand in known:
                    out.add(cand)
    for m in STR_REF.findall(src):
        add(m)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument(
        "--depth", type=int, default=1, help="reverse-import hops counted as blast radius"
    )
    ap.add_argument(
        "--hub-threshold",
        type=int,
        default=25,
        help="a module with more app dependents than this is a hub (change = wide blast)",
    )
    ap.add_argument("--hubs", choices=("unit", "skip"), default="unit")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    changed = changed_files(a.base, a.staged)
    new_files = added_files(a.base, a.staged)
    files = py_files()
    known = {mod_of(p) for p in files}
    mod_path = {mod_of(p): p for p in files}
    deps = {m: refs_of(p, m, known) for m, p in mod_path.items()}
    rev: dict[str, set[str]] = defaultdict(set)
    for m, ds in deps.items():
        for d in ds:
            rev[d].add(m)

    def app_dep(m: str) -> set[str]:
        return {x for x in rev.get(m, ()) if x.startswith("app.")}

    hubs = {m for m in known if m.startswith("app.") and len(app_dep(m)) > a.hub_threshold}
    test_files = sorted(
        str(p.relative_to(ROOT))
        for p in files
        if p.name.startswith("test_") and p.relative_to(ROOT).parts[0] == "tests"
    )
    test_text = {t: (ROOT / t).read_text(encoding="utf-8", errors="ignore") for t in test_files}

    why: dict[str, list[str]] = defaultdict(list)  # test file -> reasons
    per_file: dict[str, list[str]] = defaultdict(list)  # changed file -> tests it pulled in
    notes: list[str] = []
    ignored: list[str] = []
    uncovered: list[str] = []
    hub_changed: list[str] = []
    ruff: list[str] = []
    fe_src: list[str] = []
    fe_e2e: list[str] = []
    any_app_py = False
    new_test_added = any(
        f.startswith("tests/") and f.endswith(".py") and f.rsplit("/", 1)[-1].startswith("test_")
        for f in new_files
    )

    def pick(test: str, reason: str, src: str) -> None:
        if reason not in why[test]:
            why[test].append(reason)
        if test not in per_file[src]:
            per_file[src].append(test)

    for f in changed:
        p = ROOT / f
        is_doc = f.startswith(("studio/", "docs/")) or (
            f.endswith((".md", ".txt")) and not f.startswith("tests/")
        )
        if is_doc:
            ignored.append(f)
            continue
        if f.startswith("frontend/"):
            if f.startswith("frontend/e2e/") and f.endswith(".spec.ts"):
                fe_e2e.append(f)
            elif f.startswith(("frontend/src/", "frontend/e2e/")):
                fe_src.append(f)
            else:
                notes.append(
                    f"{f}: frontend config/dependency change -> tsc only; judge the rest by hand"
                )
                fe_src.append(f)
            continue
        if f.endswith(".py") and f.startswith(("app/", "tests/")):
            if not p.exists():
                notes.append(
                    f"{f}: deleted -> tests that referenced it fail at import (that is the signal)"
                )
                dotted = f[:-3].replace("/", ".")
                for t in test_files:
                    if dotted in test_text[t]:
                        pick(t, f"referenced deleted module {dotted}", f)
                continue
            m = mod_of(p)
            if f.startswith("app/"):
                any_app_py = True
                ruff.append(f)
                if m in hubs:
                    hub_changed.append(f"{f} ({len(app_dep(m))} dependent modules)")
                    for t in test_files:
                        if m in deps.get(mod_of(ROOT / t), set()):
                            pick(t, f"directly imports hub {m}", f)
                else:
                    seen: dict[str, int] = {m: 0}
                    frontier = [m]
                    for d in range(1, a.depth + 1):
                        nxt: list[str] = []
                        for x in frontier:
                            if x != m and x in hubs:
                                continue
                            for y in app_dep(x):
                                if y not in seen:
                                    seen[y] = d
                                    nxt.append(y)
                        frontier = nxt
                    for t in test_files:
                        hit = deps.get(mod_of(ROOT / t), set()) & seen.keys()
                        if hit:
                            best = min(hit, key=lambda h: seen[h])
                            where = (
                                "the changed module"
                                if seen[best] == 0
                                else f"{seen[best]} hop from change"
                            )
                            pick(t, f"imports {best} ({where})", f)
                stem = p.stem.lstrip("_")
                if stem and p.stem != "__init__":
                    for t in test_files:
                        if stem in Path(t).name:
                            pick(t, f"test name matches '{stem}'", f)
                    pre = stem.split("_")[0]
                    if "_" in stem and len(pre) >= 4:
                        cand = [t for t in test_files if Path(t).name.startswith(f"test_{pre}")]
                        if 0 < len(cand) <= 12:
                            for t in cand:
                                pick(t, f"test name matches family '{pre}'", f)
                    if f.startswith("app/api/") and len(stem) >= 3:
                        route = [
                            t
                            for t in test_files
                            if f'"/{stem}' in test_text[t] or f"/{stem}/" in test_text[t]
                        ]
                        for t in route[:20]:
                            pick(t, f"calls route /{stem}", f)
            else:  # a test or a test helper changed
                if p.name.startswith("test_"):
                    pick(f, "the test itself changed", f)
                elif p.name == "conftest.py":
                    d = str(p.parent.relative_to(ROOT))
                    sub = [t for t in test_files if t.startswith(d + "/")]
                    notes.append(
                        f"{f}: conftest change -> every test under {d}/ ({len(sub)} files)"
                    )
                    for t in sub:
                        pick(t, f"under changed conftest {d}/", f)
                else:
                    stack, seen_h = [m], {m}
                    while stack:
                        x = stack.pop()
                        for y in rev.get(x, ()):
                            if y not in seen_h and y.startswith("tests."):
                                seen_h.add(y)
                                stack.append(y)
                    for t in test_files:
                        if mod_of(ROOT / t) in seen_h:
                            pick(t, f"uses changed test helper {m}", f)
        elif f.startswith("app/"):
            # template / data file: link by feature word and by file name
            feat = re.search(r"/features/([^/]+)/", f)
            keys = {p.name.split(".")[0]}
            if feat:
                keys.add(feat.group(1))
            for t in test_files:
                if any(k and (k in Path(t).name or Path(f).name in test_text[t]) for k in keys):
                    pick(t, f"template/data link ({', '.join(sorted(keys))})", f)
            if f.startswith("app/core/generator/"):
                any_app_py = True
        elif f in ("tests/regression_manifest.txt", "tests/manifest_allowlist.txt"):
            notes.append(f"{f}: manifest edit -> guarded by tests/unit/test_manifest_coverage.py")
            pick("tests/unit/test_manifest_coverage.py", "manifest changed", f)
        elif f in ("pyproject.toml", "uv.lock", "Dockerfile") or f.startswith(
            ("docker/", ".github/")
        ):
            notes.append(
                f"{f}: build/dependency change -> not decidable from imports; run scripts/gate.sh quick yourself"
            )
            uncovered.append(f)
        else:
            ignored.append(f)

    # zone rules
    for f in changed:
        if f.startswith(("studio/", "docs/")):
            continue
        for rx, globs, reason in ZONES:
            if re.search(rx, f):
                for g in globs:
                    for hit in sorted(ROOT.glob(g)):
                        pick(str(hit.relative_to(ROOT)), f"zone: {reason}", f)
    if any_app_py:
        for g in GUARDS_APP:
            if (ROOT / g).exists():
                pick(g, "structural guard (cheap, any app change)", "(guards)")
    if new_test_added:
        for g in GUARD_NEW_TEST:
            if (ROOT / g).exists():
                pick(g, "new test file must be in the manifest or the allow-list", "(guards)")
    if hub_changed and a.hubs == "unit":
        for t in test_files:
            if t.startswith("tests/unit/"):
                pick(t, "hub module changed -> whole unit suite (no Docker)", "(hub)")

    for f in changed:
        if (
            f.startswith("app/")
            and f not in ignored
            and f not in uncovered
            and (ROOT / f).exists()
            and not per_file.get(f)
        ):
            uncovered.append(f)

    selected = sorted(why)
    unit = [t for t in selected if t.startswith("tests/unit/")]
    slow = [t for t in selected if t.startswith("tests/e2e/")]
    api = [t for t in selected if not t.startswith(("tests/unit/", "tests/e2e/"))]

    # frontend
    vitest = sorted(
        {
            f[len("frontend/") :]
            for f in fe_src
            if f.endswith((".ts", ".tsx")) and f.startswith("frontend/src/")
        }
    )
    specs: set[str] = {f[len("frontend/") :] for f in fe_e2e}
    spec_text = {
        s: s.read_text(encoding="utf-8", errors="ignore")
        for s in sorted((ROOT / "frontend/e2e").glob("*.spec.ts"))
    }
    wide_ui = False
    for f in fe_src:
        stem = Path(f).stem
        if f.startswith("frontend/src/") and len(stem) >= 4:
            for s, txt in spec_text.items():
                if stem in txt:
                    specs.add(f"e2e/{s.name}")
        if SHARED_FRONTEND.search(f):
            wide_ui = True
    if wide_ui:
        for n in ("visual.spec.ts", "shell-v2.spec.ts"):
            if (ROOT / "frontend/e2e" / n).exists():
                specs.add(f"e2e/{n}")

    def w(name: str, lines: list[str]) -> None:
        (out / name).write_text("".join(x + "\n" for x in lines), encoding="utf-8")

    w("ruff.txt", sorted(set(ruff)))
    w("unit.txt", unit)
    w("api.txt", api)
    w("slow.txt", slow)
    w("vitest.txt", vitest)
    w("specs.txt", sorted(specs))
    (out / "mypy.flag").write_text("1\n" if any_app_py else "", encoding="utf-8")
    (out / "tsc.flag").write_text("1\n" if fe_src else "", encoding="utf-8")

    total_unit = sum(1 for t in test_files if t.startswith("tests/unit/"))
    total_api = sum(1 for t in test_files if not t.startswith(("tests/unit/", "tests/e2e/")))
    L: list[str] = []
    L.append(f"BLAST RADIUS  (depth={a.depth}, hub threshold={a.hub_threshold}, hubs={a.hubs})")
    L.append(f"changed: {len(changed)} files | ignored (docs/studio/other): {len(ignored)}")
    for f in changed:
        if f in ignored:
            continue
        ts = per_file.get(f, [])
        L.append(f"  {f}  ->  {len(ts)} test file(s)")
        for t in ts[:6]:
            L.append(f"      {t}   [{why[t][0]}]")
        if len(ts) > 6:
            L.append(f"      ... +{len(ts) - 6} more")
    if hub_changed:
        L.append("HUB MODULES CHANGED (wide blast radius): " + "; ".join(hub_changed))
    if uncovered:
        L.append(
            "NO TEST REACHES (blind spot, add a test or check by hand): " + ", ".join(uncovered)
        )
    for n in notes:
        L.append("NOTE: " + n)
    L.append(
        f"WILL RUN : ruff {len(set(ruff))} file(s) | mypy {'yes' if any_app_py else 'no'} | "
        f"unit {len(unit)}/{total_unit} files | api {len(api)}/{total_api} files (Docker) | "
        f"slow e2e {len(slow)} (only with --slow) | tsc {'yes' if fe_src else 'no'} | "
        f"vitest related {len(vitest)} | playwright specs {len(specs)} (only with --e2e)"
    )
    L.append(
        f"UNRELATED (skipped): {total_unit - len(unit)} unit files, {total_api - len(api)} api files"
    )
    (out / "report.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
