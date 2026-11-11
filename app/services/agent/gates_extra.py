"""Gates G10-G12 of the builder agent (FX-6 / B-006): the checks the gate framework anticipated.

  G10  licence check of every hand-written requirements pin: a strong-copyleft or source-available
       licence (GPL, AGPL, SSPL, BUSL, Commons Clause; LGPL is fine) fails -> g10.licence.
       The licence is read from the metadata of the package if it is installed locally (offline,
       no network); a package that is not installed is listed as unchecked, never assumed fine.
  G11  static analysis (bandit, else semgrep) over the custom-zone Python files, ONLY when the tool is
       installed locally. Nothing is installed or downloaded. No tool = recorded as `skipped` with the
       reason, never green. Only high-severity findings fail -> g11.<tool>.
  G12  strict typing (opt-in): first the cheap pre-filter (every function of the custom Python files
       has annotated parameters and return type -> g12.untyped_def), then a REAL mypy run over the
       custom files with the generated project's own mypy config (a config that loads plugins is
       refused: plugins are code). mypy missing, timing out or crashing FAILS the gate (closed),
       it never passes -> g12.mypy_error | g12.mypy_unavailable | g12.mypy_plugin.
  G13  requirements coverage: every item of the project's requirements map is linked to a spec
       element or test (covered + covered_by), or explicitly marked out_of_scope / unmet. An item
       that is still open (never reached) fails -> g13.unreached | g13.unlinked.

Each gate reports `pass | fail | skipped` plus, for skipped, the reason (`GateReport.skipped`).
Pure reads: no project code is imported or executed (bandit and semgrep parse source only).
"""

import ast
import configparser
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.services.agent.contract import RuleFailure
from app.services.dependency_policy_service import parse_requirement

LICENCE, STATIC, TYPING, COVERAGE = "G10", "G11", "G12", "G13"
EXTRA_GATES = (LICENCE, STATIC, TYPING, COVERAGE)
CUSTOM_PY_PREFIXES = ("app/custom_routers/", "app/hooks/", "app/custom/")
TOOL_TIMEOUT = 20
MYPY_TIMEOUT = 60
MAX_COVERAGE_FAILURES = 50
TOOL_OUTPUT_CAP = 200_000
_DENIED_LICENCE = re.compile(r"(?<![A-Za-z])(AGPL|GPL|SSPL|BUSL|Commons Clause)", re.IGNORECASE)
_LGPL = re.compile(r"\bLGPL|Lesser General Public", re.IGNORECASE)


@dataclass
class ExtraResult:
    failures: list[RuleFailure] = field(default_factory=list)
    gates: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)  # gate -> why it did not run

    def skip(self, gate: str, reason: str) -> None:
        self.gates[gate] = "skipped"
        self.skipped[gate] = reason


def _fail(rule: str, loc: str, expected: str, actual: str, hint: str = "") -> RuleFailure:
    return RuleFailure(rule, loc[:300], expected, actual[:300], hint)


# -- G10 --------------------------------------------------------------------------------------


def licence_of(name: str) -> str | None:
    """The licence text of an INSTALLED package (metadata only), else None."""
    try:
        meta = importlib.metadata.metadata(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    parts = [meta.get("License-Expression") or "", meta.get("License") or ""]
    parts += [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    text = " ; ".join(p for p in parts if p).strip()
    return text[:300] or None


def denied_licence(text: str) -> bool:
    """Strong copyleft / source-available. LGPL is allowed."""
    cleaned = _LGPL.sub("", text)
    return bool(_DENIED_LICENCE.search(cleaned))


def licence_gate(
    reqs: dict[str, str], lookup: Callable[[str], str | None] = licence_of
) -> ExtraResult:
    """`reqs`: {requirements file path: text} of the hand-written (non-generated) files."""
    res = ExtraResult()
    pins: list[tuple[str, str, str]] = []
    for rel, text in sorted(reqs.items()):
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                name, _version, _hashes = parse_requirement(line)
            except ValueError:
                continue  # G8 already refuses an unparseable line
            pins.append((rel, name, line))
    if not pins:
        res.skip(LICENCE, "no hand-written requirements to check")
        return res
    unknown: list[str] = []
    for rel, name, _line in pins:
        found = lookup(name)
        if found is None:
            unknown.append(name)
        elif denied_licence(found):
            res.failures.append(_fail("g10.licence", rel, "a permissive or weak-copyleft licence",
                                      f"{name}: {found[:80]}", "use another library"))
    if res.failures:
        res.gates[LICENCE] = "fail"
    elif len(unknown) == len(pins):
        res.skip(LICENCE, f"licence unknown (package not installed locally): {', '.join(sorted(set(unknown)))[:200]}")
    else:
        res.gates[LICENCE] = "pass"
        if unknown:
            res.skipped[LICENCE] = f"checked all but: {', '.join(sorted(set(unknown)))[:200]} (not installed locally)"
    return res


# -- G11 --------------------------------------------------------------------------------------

Runner = Callable[[list[str], Path], tuple[int, str]]


def _run(argv: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603 - fixed argv of a local analysis tool, no shell, no network use
        argv, cwd=cwd, capture_output=True, timeout=TOOL_TIMEOUT, check=False,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")[:TOOL_OUTPUT_CAP]


def static_gate(
    root: Path, files: Iterable[str], *, which: Callable[[str], str | None] = shutil.which, runner: Runner = _run
) -> ExtraResult:
    res = ExtraResult()
    targets = sorted(f for f in files if f.endswith(".py") and f.startswith((*CUSTOM_PY_PREFIXES, "tests/custom/")))
    tool = next((t for t in ("bandit",) if which(t)), None)
    if tool is None:
        res.skip(STATIC, "no static-analysis tool (bandit) is installed locally; semgrep is not used because its rules come from the network")
        return res
    if not targets:
        res.skip(STATIC, "no custom Python files to analyse")
        return res
    try:
        if tool == "bandit":
            code, out = runner(["bandit", "-q", "-f", "json", "--ignore-nosec", "--severity-level", "high", *targets], root)
            findings = [(r.get("filename", ""), r.get("test_id", "B000"), r.get("line_number", 0),
                         r.get("issue_text", "")) for r in json.loads(out or "{}").get("results", [])]  # fmt: skip
    except (subprocess.SubprocessError, OSError, ValueError, AttributeError):
        res.skip(STATIC, f"{tool} could not be run or its output could not be read")
        return res
    if code not in (0, 1) and not findings:
        res.skip(STATIC, f"{tool} failed to run (exit {code})")
        return res
    for filename, rule, line, text in findings[:50]:
        res.failures.append(_fail(f"g11.{tool}", f"{filename}:{line}", "no high-severity finding", f"{rule}: {text}"[:300]))
    res.gates[STATIC] = "fail" if res.failures else "pass"
    return res


# -- G12 --------------------------------------------------------------------------------------


MYPY_CONFIG_FILES = ("mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg")
_MYPY_LINE = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:\d+:)? error: (?P<msg>.*?)(?:  \[(?P<code>[a-z0-9-]+)\])?$")


def mypy_available() -> bool:
    return importlib.util.find_spec("mypy") is not None


def _mypy_config(root: Path) -> tuple[Path | None, bool]:
    """(config file of the generated project or None, True if it loads plugins). Config is read,
    never executed; only a `plugins` entry (code) makes it unacceptable."""
    for name in MYPY_CONFIG_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text("utf-8", "replace")[:200_000]
            if name == "pyproject.toml":
                conf = tomllib.loads(text).get("tool", {}).get("mypy")
                if conf is None:
                    continue
                return path, "plugins" in json.dumps(conf)
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_string(text)
            sections = [s for s in cp.sections() if s == "mypy" or s.startswith("mypy-")]
            if not sections:
                continue
            return path, any(cp.has_option(s, "plugins") for s in sections)
        except (configparser.Error, ValueError, OSError):
            return path, True  # an unreadable config is not trusted
    return None, False


def _mypy_argv(root: Path, targets: list[str]) -> tuple[list[str], str | None]:
    config, plugins = _mypy_config(root)
    if plugins:
        return [], f"{config.name if config else 'mypy config'} loads mypy plugins, which would run project code"
    argv = [sys.executable, "-m", "mypy", "--no-error-summary", "--no-pretty", "--show-column-numbers",
            "--no-incremental", "--cache-dir", os.devnull, "--follow-imports=silent"]  # fmt: skip
    argv += ["--config-file", str(config)] if config else ["--ignore-missing-imports"]
    return [*argv, *targets], None


def _typing_untyped_defs(root: Path, targets: list[str]) -> list[RuleFailure]:
    out: list[RuleFailure] = []
    for rel in targets:
        try:
            mod = ast.parse((root / rel).read_bytes())
        except (SyntaxError, ValueError, OSError):
            continue  # G8 reports files that do not parse
        for node in ast.walk(mod):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            a = node.args
            params = [*a.posonlyargs, *a.args, *a.kwonlyargs, *([a.vararg] if a.vararg else []),
                      *([a.kwarg] if a.kwarg else [])]  # fmt: skip
            missing = [p.arg for p in params if p.annotation is None and p.arg not in ("self", "cls")]
            if missing or node.returns is None:
                what = ("parameter " + ", ".join(missing[:3])) if missing else "return type"
                out.append(_fail("g12.untyped_def", f"{rel}:{node.lineno}", "fully annotated function",
                                 f"{node.name}: missing {what}", "annotate parameters and return type"))
    return out


def typing_gate(
    root: Path,
    files: Iterable[str],
    enabled: bool,
    *,
    runner: Runner | None = None,
    available: Callable[[], bool] = mypy_available,
) -> ExtraResult:
    res = ExtraResult()
    if not enabled:
        res.skip(TYPING, "strict typing is not enabled (agent_gate_strict_typing)")
        return res
    targets = sorted(f for f in files if f.endswith(".py") and f.startswith(CUSTOM_PY_PREFIXES))
    if not targets:
        res.skip(TYPING, "no custom Python files to check")
        return res
    res.failures += _typing_untyped_defs(root, targets)  # cheap pre-filter, reported even if mypy is absent
    if res.failures:
        res.gates[TYPING] = "fail"  # fix the annotations first; mypy would only repeat them
        return res
    if not available():
        res.failures.append(_fail("g12.mypy_unavailable", "mypy", "mypy installed in the platform environment",
                                  "mypy is not available, so the code could not be type-checked",
                                  "install mypy; the gate never passes unchecked code"))
        res.gates[TYPING] = "fail"
        return res
    argv, refused = _mypy_argv(root, targets)
    if refused:
        res.failures.append(_fail("g12.mypy_plugin", "mypy config", "a mypy config without plugins", refused,
                                  "remove the plugins entry"))
        res.gates[TYPING] = "fail"
        return res
    run = runner or _run_mypy
    try:
        code, out = run(argv, root)
    except subprocess.TimeoutExpired:
        code, out = -1, f"mypy timed out after {MYPY_TIMEOUT}s"
    except (subprocess.SubprocessError, OSError) as exc:
        code, out = -1, f"mypy could not be run: {type(exc).__name__}"
    found = [m for m in (_MYPY_LINE.match(line.strip()) for line in out.splitlines()) if m]
    for m in found[:MAX_COVERAGE_FAILURES]:
        suffix = f" [{m['code']}]" if m["code"] else ""
        res.failures.append(_fail("g12.mypy_error", f"{m['file']}:{m['line']}", "code that type-checks",
                                  f"{m['msg']}{suffix}", "fix the type error"))
    if not found and code != 0:  # crash, timeout, config error: closed, not green
        res.failures.append(_fail("g12.mypy_unavailable", "mypy", "a completed mypy run",
                                  f"mypy did not finish cleanly (exit {code}): {out.strip()[:200]}", "see the tool output"))
    res.gates[TYPING] = "fail" if res.failures else "pass"
    return res


def _run_mypy(argv: list[str], cwd: Path) -> tuple[int, str]:
    """mypy over local files only: no shell, empty-ish environment (no proxies), the cache disabled."""
    proc = subprocess.run(  # noqa: S603 - fixed argv of the local mypy, no shell, no network use
        argv, cwd=cwd, capture_output=True, timeout=MYPY_TIMEOUT, check=False,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")[:TOOL_OUTPUT_CAP]


# -- G13 --------------------------------------------------------------------------------------


def coverage_gate(items: Iterable[dict[str, object]] | None) -> ExtraResult:
    """`items`: the requirement items of the run's requirements map ({id, kind, text, status,
    covered_by}); None = the project has no requirements map. Pure, no I/O."""
    res = ExtraResult()
    if items is None:
        res.skip(COVERAGE, "no requirements map for this project")
        return res
    reqs = [i for i in items if i.get("kind") != "out_of_scope"]
    if not reqs:
        res.skip(COVERAGE, "the requirements map has no requirements to cover")
        return res
    unmet: list[str] = []
    for it in sorted(reqs, key=lambda i: str(i.get("id", ""))):
        status, rid = str(it.get("status") or "open"), str(it.get("id", ""))[:8]
        text = str(it.get("text", ""))[:150]
        loc = f"requirement:{rid}"
        if status == "out_of_scope":
            continue
        if status == "unmet":
            unmet.append(rid)
        elif status == "covered":
            if not str(it.get("covered_by") or "").strip():
                res.failures.append(_fail("g13.unlinked", loc, "a covered requirement links to a spec element or test",
                                          f"[{it.get('kind')}] {text} is marked covered but links to nothing",
                                          "set covered_by to the spec element or test, or mark it unmet"))
        else:
            res.failures.append(_fail("g13.unreached", loc, "linked to a spec element or test, or explicitly marked unmet",
                                      f"[{it.get('kind')}] {text}", "build it and link it (covered_by), or mark it unmet"))
    if len(res.failures) > MAX_COVERAGE_FAILURES:
        extra = len(res.failures) - MAX_COVERAGE_FAILURES
        res.failures = res.failures[:MAX_COVERAGE_FAILURES]
        res.failures.append(_fail("g13.more", "requirements", "every requirement covered", f"{extra} more unreached"))
    res.gates[COVERAGE] = "fail" if res.failures else "pass"
    if unmet and not res.failures:
        res.skipped[COVERAGE] = f"{len(unmet)} requirement(s) explicitly marked unmet: {', '.join(unmet[:10])}"
    return res
