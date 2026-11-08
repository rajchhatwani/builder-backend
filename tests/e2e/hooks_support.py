"""Shared pieces of the hook end-to-end tests: the extended example spec, the hook bodies an author would
write, and helpers that write them into a generated project and run the gate."""

import copy
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"

MATCH_BODY = """
from decimal import Decimal

from app.platform_sdk import pct_diff

if data.invoice_no == "RAISE":
    raise ValueError("boom")
if data.invoice_no == "DENY" or pct_diff(data.amount, data.po_amount) > Decimal("50"):
    return MatchResult(allowed=False, reason="variance too high")
return MatchResult(allowed=True)
"""

NOTIFY_BODY = """
from app.platform_sdk import find_rows, log, now

if data.invoice_no == "EFFECT-FAIL":
    raise ValueError("boom")
rows = find_rows("Invoice", invoice_no=data.invoice_no, limit=5)
log.info("notified", at=now().isoformat(), same=len(rows), status=data.status)
return NotifyResult(sent=True)
"""

NORMALIZE_BODY = """
return NormalizeResult(invoice_no=data.invoice_no.strip())
"""

FALLBACK_BODY = """
return DefaultPoResult(po_amount=data.amount)
"""

CHECK_BODY = """
if data.amount > 1000000:
    return CheckResult(valid=False, message="amount is too large")
return CheckResult(valid=True)
"""

AUDIT_BODY = """
if data.invoice_no == "FAIL-AFTER-SAVE":
    raise ValueError("boom")
return AuditResult(ok=True)
"""


def example_spec() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "hooks_invoice.json").read_text(encoding="utf-8"))
    return data


def _hook(name: str, point: str, in_model: str, out_model: str, inputs: list[tuple[str, str]],
          outputs: list[tuple[str, str, bool]], **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "point": point,
        "kind": "pure",
        "input": {"name": in_model, "fields": [{"name": n, "type": t, "required": True} for n, t in inputs]},
        "output": {"name": out_model, "fields": [{"name": n, "type": t, "required": r} for n, t, r in outputs]},
        "budget": {"cpu_ms": 300, "rows": 0, "outbound_calls": 0},
        **extra,
    }


def points_spec() -> dict[str, Any]:
    """hooks_invoice plus a hook at every other point of the lifecycle chain."""
    data = copy.deepcopy(example_spec())
    data["project"].update(name="Invoice Points", slug="hooks-points")
    data["hooks"] += [
        _hook("normalize_no", "Invoice.before_save", "NormalizeInput", "NormalizeResult",
              [("invoice_no", "string")], [("invoice_no", "string", False)]),
        _hook("default_po", "Invoice.before_save", "DefaultPoInput", "DefaultPoResult",
              [("amount", "decimal")], [("po_amount", "decimal", False)],
              failure_policy="fallback", fallback={"po_amount": "1.00"}),
        _hook("check_amounts", "Invoice.validate", "CheckInput", "CheckResult",
              [("invoice_no", "string"), ("amount", "decimal"), ("po_amount", "decimal")],
              [("valid", "bool", True), ("message", "string", False)]),
        _hook("audit_save", "Invoice.after_save", "AuditInput", "AuditResult",
              [("id", "uuid"), ("invoice_no", "string")], [("ok", "bool", True)]),
    ]
    return data


BODIES = {
    "match_invoice": MATCH_BODY,
    "notify_approved": NOTIFY_BODY,
    "normalize_no": NORMALIZE_BODY,
    "default_po": FALLBACK_BODY,
    "check_amounts": CHECK_BODY,
    "audit_save": AUDIT_BODY,
}


def generate_tree(spec_data: dict[str, Any]) -> dict[str, str]:
    return generate(Spec.model_validate(spec_data))


def with_body(stub: str, body: str) -> str:
    lines = stub.split("\n")
    start = next(i for i, line in enumerate(lines) if "<agent:body" in line)
    end = next(i for i, line in enumerate(lines) if "</agent:body>" in line)
    new = ["    " + line if line.strip() else line for line in textwrap.dedent(body).strip("\n").split("\n")]
    return "\n".join([*lines[: start + 1], *new, *lines[end:]])


def write_body(root: Path, name: str, body: str) -> None:
    path = root / "app" / "custom" / "hooks" / f"{name}.py"
    path.write_text(with_body(path.read_text(encoding="utf-8"), body), encoding="utf-8", newline="\n")


def write_good_bodies(root: Path, names: list[str]) -> None:
    for name in names:
        write_body(root, name, BODIES[name])


def run_gate(root: Path, *args: str) -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(
        [sys.executable, "-m", "app.platform_gate", *args],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    report = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, report, result.stderr
