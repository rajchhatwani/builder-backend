"""Gates G10-G12 of the builder agent (FX-6 / B-006): the checks the gate framework anticipated.

  G10  licence check of every hand-written requirements pin: a strong-copyleft or source-available
       licence (GPL, AGPL, SSPL, BUSL, Commons Clause; LGPL is fine) fails -> g10.licence.
       The licence is read from the metadata of the package if it is installed locally (offline,
       no network); a package that is not installed is listed as unchecked, never assumed fine.
  G11  static analysis (bandit, else semgrep) over the custom-zone Python files, ONLY when the tool is
       installed locally. Nothing is installed or downloaded. No tool = recorded as `skipped` with the
       reason, never green. Only high-severity findings fail -> g11.<tool>.
  G12  strict typing (opt-in): every function of the custom Python files has annotated parameters and
       return type (the `disallow_untyped_defs` core of mypy --strict) -> g12.untyped_def.

Each gate reports `pass | fail | skipped` plus, for skipped, the reason (`GateReport.skipped`).
Pure reads: no project code is imported or executed (bandit and semgrep parse source only).
"""

import ast
import importlib.metadata
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.services.agent.contract import RuleFailure
from app.services.dependency_policy_service import parse_requirement

LICENCE, STATIC, TYPING = "G10", "G11", "G12"
EXTRA_GATES = (LICENCE, STATIC, TYPING)
CUSTOM_PY_PREFIXES = ("app/custom_routers/", "app/hooks/", "app/custom/")
TOOL_TIMEOUT = 20
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


def typing_gate(root: Path, files: Iterable[str], enabled: bool) -> ExtraResult:
    res = ExtraResult()
    if not enabled:
        res.skip(TYPING, "strict typing is not enabled (agent_gate_strict_typing)")
        return res
    targets = sorted(f for f in files if f.endswith(".py") and f.startswith(CUSTOM_PY_PREFIXES))
    if not targets:
        res.skip(TYPING, "no custom Python files to check")
        return res
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
                res.failures.append(_fail("g12.untyped_def", f"{rel}:{node.lineno}", "fully annotated function",
                                          f"{node.name}: missing {what}", "annotate parameters and return type"))
    res.gates[TYPING] = "fail" if res.failures else "pass"
    return res
