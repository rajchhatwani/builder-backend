"""Gates G8 (security) and G9 (server-side replay) for the builder agent (B3-3; architecture 6.3 and
the 2026-11-01 addendum). G0-G7 are the "hook gates v1" of app/core/hook_gates.py, reused as they are.

Pure static analysis: no project code is imported, compiled to code or executed, nothing touches the
network, no external scanner is called. Everything is bounded (files, bytes, seconds).

  G8  (a) secret patterns in every non-generated file      -> g8.secret
      (b) dependency allow-list for every non-generated requirements*.txt (check_requirements with the
          owner-approved pins passed in; unknown, unpinned or hashless-approved lines fail) -> g8.dependency
      (c) tenant isolation in migrations of a multi-tenant project: every table needs a tenant_id
          column; tables created by a non-generated migration also need ENABLE ROW LEVEL SECURITY and a
          `tenant_isolation` policy -> g8.tenant_column / g8.rls_missing
          NOTE: platform-generated projects isolate tenants in the application (tenant_id filter), not
          with Postgres RLS, so generated migrations are held to the column rule only.
      (d) auth on every route written outside the generated zone, unless the (METHOD, path) is in
          `public_routes`; the guard is recognised by name (see _AUTH_GUARD)  -> g8.route_no_auth
      (e) dangerous constructs in custom Python (subprocess, sockets, ctypes, pickle, eval/exec,
          os.system ...) -> g8.banned_import / g8.banned_call
      plus structural hazards: symlinks, special files, oversized files, scan limits.
  G9  replay: regenerate from the spec into a temp dir, every generated-zone file must be byte-identical
      to the draft worktree (replay_mismatch), then G0-G8 run again on the clean copy with the custom
      and seeded files copied over from the worktree.
"""

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core import hook_gates
from app.core.generator import InvalidSpecError, generate
from app.core.spec_models import Spec
from app.services.agent import gates_extra as gx
from app.services.agent.contract import RuleFailure
from app.services.dependency_policy_service import Pin, check_requirements, is_dependency_manifest

GATE_ORDER = ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G12", "G13")
MAX_FILES = 5_000
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 64 * 1_048_576
MAX_SECONDS = 20.0
DEFAULT_PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset({("GET", "/health"), ("GET", "/ready")})
DEFAULT_CUSTOM_PREFIXES = ("app/custom_routers/", "app/hooks/", "app/custom/", "tests/custom/")

_SKIP_DIRS = hook_gates.SKIP_DIRS
_STRONG_SECRET_PATTERNS = hook_gates._SECRET_PATTERNS[:-2]  # the two generic hex/base64 ones are noisy
_BANNED_MODULES = frozenset(
    {"subprocess", "socket", "ctypes", "pickle", "marshal", "shelve", "pty", "telnetlib", "ftplib",
     "importlib", "builtins"}
)
_BANNED_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
_BANNED_OS = frozenset({"system", "popen", "execv", "execve", "execl", "execvp", "spawnl", "spawnv", "fork"})
_AUTH_GUARD = re.compile(
    r"_ACCESS|require_|get_current|current_user|current_principal|get_principal|access_dependency|"
    r"authorize|authenticate|AuthUser|CurrentUser|verify_token",
)
_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "api_route"})


@dataclass
class GateReport:
    ok: bool
    failures: list[RuleFailure] = field(default_factory=list)
    gates: dict[str, str] = field(default_factory=dict)  # "G0".."G13" -> pass | fail | skipped
    skipped: dict[str, str] = field(default_factory=dict)  # gate -> why it did not (fully) run; not in the hash


def signature(failure: RuleFailure) -> str:
    """What the loop counts repairs by: the same rule at the same place is the same problem."""
    return f"{failure.rule_id}@{failure.location}"


def report_hash(report: GateReport) -> str:
    body = {
        "ok": report.ok,
        "gates": dict(sorted(report.gates.items())),
        "failures": [f.as_dict() for f in report.failures],
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _loc(rel: str) -> str:
    """A path safe to put in a report: control and non-ASCII characters are escaped."""
    clean = "".join(c if c.isascii() and c.isprintable() else f"\\x{ord(c):x}" for c in rel)
    return clean[:300]


def _fail(rule: str, loc: str, expected: str, actual: str, hint: str = "") -> RuleFailure:
    return RuleFailure(rule, _loc(loc), expected, actual[:300], hint)


def _order(failures: Iterable[RuleFailure]) -> list[RuleFailure]:
    uniq = {(f.rule_id, f.location, f.actual): f for f in failures}
    return [uniq[k] for k in sorted(uniq)]


# -- bounded, hazard-aware tree walk ------------------------------------------------------------
@dataclass
class _Tree:
    files: dict[str, int] = field(default_factory=dict)  # rel path -> size (regular files only)
    failures: list[RuleFailure] = field(default_factory=list)
    hazard: bool = False  # a symlink or special file: nothing may follow paths blindly


def _scan_tree(root: Path, deadline: float) -> _Tree:
    tree = _Tree()
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        keep = []
        for d in dirnames:
            full = Path(dirpath, d)
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                tree.hazard = True
                tree.failures.append(_fail("g8.symlink", rel, "no symbolic links", "directory symlink",
                                           "remove the link; it is never followed"))
            elif d == ".git" and full.parent == root:
                continue  # only the checkout's own git data; every other directory is scanned (S1-002)
            else:
                keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            if time.monotonic() > deadline or len(tree.files) >= MAX_FILES:
                tree.failures.append(_fail("g8.scan_limit", ".", f"at most {MAX_FILES} files in time",
                                           "scan stopped", "too many files or too slow"))
                tree.hazard = True
                return tree
            full = Path(dirpath, name)
            rel = full.relative_to(root).as_posix()
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                tree.hazard = True
                tree.failures.append(_fail("g8.symlink", rel, "no symbolic links", "file symlink",
                                           "remove the link; it is never followed"))
            elif not stat.S_ISREG(st.st_mode):
                tree.hazard = True
                tree.failures.append(_fail("g8.special_file", rel, "regular files only", "special file"))
            else:
                total += st.st_size
                tree.files[rel] = st.st_size
                if any(part in _SKIP_DIRS for part in rel.split("/")[:-1]):
                    # Cache/tool dirs were once skipped by every check; a file here would bypass G8,
                    # replay and the content hash. It is now covered by all three AND a failure.
                    tree.failures.append(_fail("g8.cache_dir_file", rel, "no files in cache or tool directories",
                                               "file under a skipped directory", "delete the directory"))
                if total > MAX_TOTAL_BYTES:
                    tree.failures.append(_fail("g8.scan_limit", ".", f"at most {MAX_TOTAL_BYTES} bytes",
                                               "project too large"))
                    tree.hazard = True
                    return tree
    return tree


def _read(root: Path, rel: str, size: int, cap: int = MAX_FILE_BYTES) -> bytes | None:
    if size > cap:
        return None
    try:
        with open(root / rel, "rb") as fh:
            return fh.read(cap + 1)[:cap]
    except OSError:
        return None


def _json(root: Path, tree: _Tree, rel: str) -> dict[str, Any] | None:
    if rel not in tree.files:
        return None
    raw = _read(root, rel, tree.files[rel], 5_000_000)
    try:
        data = json.loads(raw.decode("utf-8")) if raw is not None else None
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


# -- G0-G7 -------------------------------------------------------------------------------------
def _hook_gates(root: Path, spec: Spec, tree: _Tree) -> tuple[list[RuleFailure], dict[str, str]]:
    gates = {g: "pass" for g in GATE_ORDER[:8]}
    has_manifest = hook_gates.MANIFEST_PATH in tree.files
    if tree.hazard:
        return [], {g: "skipped" for g in GATE_ORDER[:8]}
    if not has_manifest and not spec.hooks:
        return [], {g: "skipped" for g in GATE_ORDER[:8]}  # no hooks: nothing for G0-G7 to look at
    findings, _checked = hook_gates.check_project(root)
    out = []
    for f in findings:
        gates[f.gate] = "fail"
        out.append(_fail(f.rule, f.file, "no finding", f"line {f.line}: {f.message}"))
    return out, gates


# -- G8 ----------------------------------------------------------------------------------------
def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _parse(raw: bytes) -> ast.Module | None:
    try:
        return ast.parse(raw.decode("utf-8"))
    except (SyntaxError, ValueError, RecursionError, MemoryError, UnicodeDecodeError):
        return None


def _check_banned(rel: str, mod: ast.Module) -> list[RuleFailure]:
    out: list[RuleFailure] = []
    os_names = {"os"}  # local names bound to the os module
    for node in ast.walk(mod):
        if isinstance(node, ast.Import):
            os_names.update(a.asname or a.name for a in node.names if a.name == "os")
    for node in ast.walk(mod):
        where = f"{rel}:{getattr(node, 'lineno', 1)}"
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                if n.split(".")[0] in _BANNED_MODULES:
                    out.append(_fail("g8.banned_import", where, "no process/socket/pickle/importlib modules",
                                     f"imports {n.split('.')[0]}", "use the platform SDK instead"))
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "os":
                for a in node.names:
                    if a.name in _BANNED_OS or a.name == "*":
                        out.append(_fail("g8.banned_import", where, "no process calls from os",
                                         f"imports os.{a.name}", "use the platform SDK instead"))
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            root, _, rest = name.partition(".")
            if name in _BANNED_CALLS or (root in os_names and rest in _BANNED_OS):
                out.append(_fail("g8.banned_call", where, "no dynamic code or process calls", f"calls {name}"))
        elif (isinstance(node, ast.Name) and node.id == "__builtins__") or (
            isinstance(node, ast.Attribute) and node.attr == "__builtins__"
        ):
            out.append(_fail("g8.banned_name", where, "no access to __builtins__", "uses __builtins__"))
    return out


check_banned = _check_banned


def _is_guard(call: ast.Call) -> bool:
    fn = _dotted(call.func).rsplit(".", 1)[-1]
    return fn in {"Depends", "Security"} and bool(_AUTH_GUARD.search(ast.unparse(call)))


def _has_guard(nodes: Iterable[ast.AST]) -> bool:
    return any(isinstance(n, ast.Call) and _is_guard(n) for top in nodes for n in ast.walk(top))


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _check_routes(rel: str, mod: ast.Module, public: frozenset[tuple[str, str]]) -> list[RuleFailure]:
    routers: dict[str, tuple[str, bool]] = {}  # variable -> (prefix, router-level guard)
    for node in ast.walk(mod):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _dotted(node.value.func).rsplit(".", 1)[-1] == "APIRouter":
                kw = {k.arg: k.value for k in node.value.keywords if k.arg}
                prefix = _const_str(kw.get("prefix")) or ""
                guarded = "dependencies" in kw and _has_guard([kw["dependencies"]])
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        routers[t.id] = (prefix, guarded)
    out: list[RuleFailure] = []
    for node in ast.walk(mod):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if dec.func.attr not in _ROUTE_METHODS:
                continue
            owner = _dotted(dec.func.value)
            prefix, router_guard = routers.get(owner, ("", False))
            path = _const_str(dec.args[0]) if dec.args else None
            methods = [dec.func.attr.upper()] if dec.func.attr != "api_route" else ["*"]
            full = prefix + (path or "")
            if router_guard or any((m, full) in public for m in methods):
                continue
            params = [*node.args.args, *node.args.kwonlyargs]
            parts: list[ast.AST] = [dec, *[a.annotation for a in params if a.annotation is not None],
                                    *node.args.defaults, *[d for d in node.args.kw_defaults if d]]
            if not _has_guard(parts):
                out.append(_fail("g8.route_no_auth", f"{rel}:{node.lineno}", "an auth guard dependency",
                                 f"{methods[0]} {_loc(full) or '?'} has none",
                                 "add Depends(<auth guard>) or declare the route public"))
    return out


def _tenant_columns_and_tables(mod: ast.Module) -> tuple[dict[str, bool], set[str], str]:
    """(created tables -> has an `id` column, tables that get tenant_id, all string constants joined)."""
    created: dict[str, bool] = {}
    tenant: set[str] = set()
    strings: list[str] = []
    for node in ast.walk(mod):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        cols = [a for a in ast.walk(node) if isinstance(a, ast.Call) and _dotted(a.func).endswith("Column")]
        names = [_const_str(c.args[0]) for c in cols if c.args]
        if attr == "create_table" and node.args and (t := _const_str(node.args[0])):
            created[t] = "id" in names
            if "tenant_id" in names:
                tenant.add(t)
        elif attr == "add_column" and node.args and (t := _const_str(node.args[0])):
            if "tenant_id" in names:
                tenant.add(t)
    return created, tenant, "\n".join(strings)


def _check_tenancy(
    root: Path, tree: _Tree, zones: dict[str, str], spec: Spec
) -> list[RuleFailure]:
    if spec.auth is None or not spec.auth.enabled or not spec.auth.multi_tenant:
        return []
    out: list[RuleFailure] = []
    infos: list[tuple[str, bool, dict[str, bool], set[str], str]] = []
    for rel in sorted(tree.files):
        if not (rel.startswith("alembic/versions/") and rel.endswith(".py")):
            continue
        raw = _read(root, rel, tree.files[rel])
        mod = _parse(raw) if raw is not None else None
        if mod is None:
            out.append(_fail("g8.migration_unreadable", rel, "a parsable migration", "cannot parse"))
            continue
        created, tenant, text = _tenant_columns_and_tables(mod)
        infos.append((rel, zones.get(rel) == "generated", created, tenant, text))
    tenant_tables = {t for *_x, tenant, _t in infos for t in tenant}
    entity_tables = {e.table_name for e in spec.entities}
    for rel, generated, created, _tenant, text in infos:
        for table, has_id in sorted(created.items()):
            if table.startswith("auth_") or table == "alembic_version" or not has_id:
                continue  # platform auth tables, and association tables without an id
            if generated and table not in entity_tables:
                continue  # platform-owned tables of other modules (payments, storage ...)
            if table not in tenant_tables:
                out.append(_fail("g8.tenant_column", f"{rel}:{table}", "a tenant_id column",
                                 f"table {table} has none", "every table of a multi-tenant project is tenant-scoped"))
                continue
            if generated:
                continue
            t = re.escape(table)
            enabled = re.search(rf"ALTER\s+TABLE\s+\"?{t}\"?\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", text, re.I)
            policy = re.search(rf"CREATE\s+POLICY\s+\"?\w*tenant_isolation\w*\"?\s+ON\s+\"?{t}\"?", text, re.I)
            if not (enabled and policy):
                out.append(_fail("g8.rls_missing", f"{rel}:{table}", "ENABLE ROW LEVEL SECURITY + a tenant_isolation policy",
                                 f"table {table} lacks " + ("both" if not (enabled or policy) else "one of them"),
                                 "add both statements with op.execute in the same migration"))
    return out


def _dependency_failures(
    root: Path, tree: _Tree, zones: dict[str, str], approved: Iterable[Pin]
) -> list[RuleFailure]:
    out: list[RuleFailure] = []
    pins = list(approved)
    for rel in sorted(tree.files):
        name = rel.rsplit("/", 1)[-1]
        if zones.get(rel) == "generated":
            continue
        if not (name.startswith("requirements") and name.endswith(".txt")):
            if is_dependency_manifest(rel):  # any other way to declare a package is refused outright
                out.append(_fail("g8.dependency", rel, "no hand-written dependency manifest",
                                 f"{name} can declare packages", "use request_dependency"))
            continue
        raw = _read(root, rel, tree.files[rel])
        if raw is None:
            out.append(_fail("g8.file_too_large", rel, f"at most {MAX_FILE_BYTES} bytes", "file too large"))
            continue
        verdict = check_requirements(raw.decode("utf-8", "replace"), pins)
        for r in verdict.blocked:
            out.append(_fail("g8.dependency", rel, "an allow-listed or owner-approved exact pin",
                             f"{r.line[:80]!r}: {r.reason}", "use request_dependency"))
    return out


def _g8(
    root: Path, spec: Spec, tree: _Tree, approved: Iterable[Pin], public: frozenset[tuple[str, str]]
) -> list[RuleFailure]:
    out: list[RuleFailure] = list(tree.failures)
    zones_doc = _json(root, tree, hook_gates.ZONES_PATH)
    if zones_doc is None:
        out.append(_fail("g8.zones_missing", hook_gates.ZONES_PATH, "a readable zone manifest", "missing or invalid"))
        zones: dict[str, str] = {}
    else:
        zones = {k: v for k, v in (zones_doc.get("zones") or {}).items() if isinstance(v, str)}
    auth_on = spec.auth is not None and spec.auth.enabled
    for rel in sorted(tree.files):
        generated = zones.get(rel) == "generated"
        raw = _read(root, rel, tree.files[rel])
        if raw is None:
            if not generated:
                out.append(_fail("g8.file_too_large", rel, f"at most {MAX_FILE_BYTES} bytes",
                                 f"{tree.files[rel]} bytes", "split or remove the file"))
            continue
        if not generated and b"\x00" not in raw[:8192]:
            text = raw.decode("utf-8", "replace")
            for pat in _STRONG_SECRET_PATTERNS:
                m = pat.search(text)
                if m:
                    line = text.count("\n", 0, m.start()) + 1
                    out.append(_fail("g8.secret", f"{rel}:{line}", "no secret-looking literal",
                                     "a secret-like value (not shown)", "use the platform secret store"))
                    break
        if generated or not rel.endswith(".py"):
            continue
        in_code_zone = rel.startswith(("app/", "tests/"))
        mod = _parse(raw) if in_code_zone else None
        if in_code_zone and mod is None:
            out.append(_fail("g8.syntax_error", rel, "valid Python", "does not parse"))
        if mod is not None:
            out.extend(_check_banned(rel, mod))
            if auth_on and rel.startswith("app/"):
                out.extend(_check_routes(rel, mod, public))
    out.extend(_dependency_failures(root, tree, zones, approved))
    out.extend(_check_tenancy(root, tree, zones, spec))
    return out


# -- public API -----------------------------------------------------------------------------------
def run_gates(
    root: Path,
    spec: Spec,
    *,
    approved_pins: Iterable[Pin] = (),
    upto: str = "G8",
    public_routes: Iterable[tuple[str, str]] = DEFAULT_PUBLIC_ROUTES,
    max_seconds: float = MAX_SECONDS,
    licence: bool = True,
    static_analysis: bool = True,
    strict_typing: bool = False,
    requirements: list[dict[str, Any]] | None = None,
) -> GateReport:
    """G0-G7 (hook gates) and, when `upto` is G8, the security gate plus the extra gates G10-G13
    (gates_extra). Never executes project code."""
    if upto not in ("G7", "G8"):
        raise ValueError("upto must be 'G7' or 'G8' (G9 is replay())")
    root = Path(root)
    tree = _scan_tree(root, time.monotonic() + max_seconds)
    failures, gates = _hook_gates(root, spec, tree)
    for g in ("G8", "G9", *gx.EXTRA_GATES):
        gates[g] = "skipped"
    skipped: dict[str, str] = {}
    if upto == "G8":
        g8 = _g8(root, spec, tree, tuple(approved_pins), frozenset(public_routes))
        failures += g8
        gates["G8"] = "fail" if g8 else "pass"
        if not tree.hazard:
            for ex in _extras(root, tree, licence, static_analysis, strict_typing, requirements):
                failures += ex.failures
                gates.update(ex.gates)
                skipped.update(ex.skipped)
    elif tree.failures:
        failures += tree.failures
    ordered = _order(failures)
    return GateReport(ok=not ordered, failures=ordered, gates=gates, skipped=skipped)


def _extras(
    root: Path, tree: _Tree, licence: bool, static_analysis: bool, strict_typing: bool,
    requirements: list[dict[str, Any]] | None = None,
) -> list[gx.ExtraResult]:
    zones_doc = _json(root, tree, hook_gates.ZONES_PATH) or {}
    zones = {k: v for k, v in (zones_doc.get("zones") or {}).items() if isinstance(v, str)}
    out: list[gx.ExtraResult] = []
    if licence:
        reqs: dict[str, str] = {}
        for rel in sorted(tree.files):
            name = rel.rsplit("/", 1)[-1]
            if zones.get(rel) != "generated" and name.startswith("requirements") and name.endswith(".txt"):
                raw = _read(root, rel, tree.files[rel])
                if raw is not None:
                    reqs[rel] = raw.decode("utf-8", "replace")
        out.append(gx.licence_gate(reqs))
    if static_analysis:
        out.append(gx.static_gate(root, tree.files))
    out.append(gx.typing_gate(root, tree.files, strict_typing))
    out.append(gx.coverage_gate(requirements))
    return out


def _write_clean(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        parts = Path(rel).parts
        if Path(rel).is_absolute() or ".." in parts or not parts:
            raise ValueError(f"generated path not allowed: {rel!r}")
        target = base.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))


def replay(
    root: Path,
    spec: Spec,
    approved_pins: Iterable[Pin] = (),
    *,
    public_routes: Iterable[tuple[str, str]] = DEFAULT_PUBLIC_ROUTES,
    max_seconds: float = MAX_SECONDS,
    licence: bool = True,
    static_analysis: bool = True,
    strict_typing: bool = False,
) -> GateReport:
    """G9: regenerate from the spec, compare every generated-zone file byte for byte with the worktree,
    then run G0-G8 on the clean copy (custom and seeded files copied from the worktree)."""
    root = Path(root)
    pins = tuple(approved_pins)
    tree = _scan_tree(root, time.monotonic() + max_seconds)
    failures: list[RuleFailure] = list(tree.failures)
    try:
        files = generate(spec)
    except InvalidSpecError as exc:
        f = _fail("replay_spec_invalid", "spec", "a valid spec", f"{len(exc.issues)} validation issue(s)")
        return GateReport(False, [f], {**{g: "skipped" for g in GATE_ORDER}, "G9": "fail"})
    zones_doc: dict[str, Any] = {}
    try:
        zones_doc = json.loads(files.get(hook_gates.ZONES_PATH, "{}"))
    except ValueError:
        pass
    zones = {k: v for k, v in (zones_doc.get("zones") or {}).items() if isinstance(v, str)}
    prefixes = DEFAULT_CUSTOM_PREFIXES
    try:
        manifest = json.loads(files.get(hook_gates.MANIFEST_PATH, "{}"))
        prefixes = tuple({*prefixes, *manifest.get("custom_prefixes", [])})
    except ValueError:
        pass

    for rel in sorted(files):
        if zones.get(rel, "generated") != "generated":
            continue
        want = files[rel].encode("utf-8")
        if rel not in tree.files:
            failures.append(_fail("replay_mismatch", rel, "byte-identical to the regenerated file", "missing"))
            continue
        raw = _read(root, rel, tree.files[rel], len(want)) if tree.files[rel] == len(want) else None
        if raw != want:
            failures.append(_fail("replay_mismatch", rel, "byte-identical to the regenerated file", "content differs"))
    for rel in sorted(tree.files):
        if rel in files or rel.startswith(prefixes) or rel == ".git" or rel.startswith(".git/"):
            continue  # a worktree's .git pointer file is the checkout itself, not project content
        failures.append(_fail("replay_mismatch", rel, "a file the platform generated or a custom-zone file",
                              "unexpected file", "remove it or move it into a custom zone"))

    gates = {g: "skipped" for g in GATE_ORDER}
    skipped: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="bb-replay-") as tmp:
        clean = Path(tmp) / "clean"
        _write_clean(clean, files)
        if not tree.hazard:
            for rel, size in sorted(tree.files.items()):
                keep = zones.get(rel) in ("custom", "seeded") or (rel not in files and rel.startswith(prefixes))
                if not keep:
                    continue
                raw = _read(root, rel, size)
                if raw is None:
                    failures.append(_fail("g8.file_too_large", rel, f"at most {MAX_FILE_BYTES} bytes", f"{size} bytes"))
                    continue
                target = clean.joinpath(*Path(rel).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            inner = run_gates(clean, spec, approved_pins=pins, upto="G8", public_routes=public_routes,
                              max_seconds=max_seconds, licence=licence, static_analysis=static_analysis,
                              strict_typing=strict_typing)
            failures += inner.failures
            gates.update(inner.gates)
            skipped.update(inner.skipped)
        shutil.rmtree(clean, ignore_errors=True)
    ordered = _order(failures)
    mismatch = any(f.rule_id == "replay_mismatch" for f in ordered)
    gates["G9"] = "fail" if mismatch else "pass"
    return GateReport(ok=not ordered, failures=ordered, gates=gates, skipped=skipped)
