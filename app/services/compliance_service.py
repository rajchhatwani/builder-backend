"""Control mapping and evidence bundle (D47): built purely from a Spec, no database access.

`controls_for` answers which controls of a framework the spec meets; `evidence_bundle` packs the
answer, the spec facts behind it, and the tests that prove it into a deterministic zip."""

import hashlib
import io
import json
import re
import zipfile
from typing import Any

from app.core.compliance_controls import CONTROLS, FRAMEWORKS, evaluate
from app.core.spec_models import Spec, spec_hash
from app.core.validation_providers import secret_key_name, secret_value
from app.exceptions import AppError

ZIP_DATE = (2020, 1, 1, 0, 0, 0)
FRAMEWORK_LABELS = {"soc2": "SOC 2", "hipaa": "HIPAA Security Rule", "pci": "PCI DSS"}
TEST_COMMAND = "pytest -q tests/ -k \"{names}\""
REDACTED = "[redacted]"


def _check_framework(framework: str | None) -> list[str]:
    if framework is None:
        return list(FRAMEWORKS)
    if framework not in FRAMEWORKS:
        raise AppError(code="invalid_framework", message=f"framework must be one of {', '.join(FRAMEWORKS)}",
                       status_code=422)
    return [framework]


def controls_for(spec: Spec, framework: str | None = None) -> dict[str, Any]:
    frameworks = _check_framework(framework)
    rows = [evaluate(c, spec) for c in CONTROLS if c.framework in frameworks]
    return {
        "framework": framework or "all",
        "met": sum(r["status"] == "met" for r in rows),
        "unmet": sum(r["status"] == "unmet" for r in rows),
        "not_applicable": sum(r["status"] == "not_applicable" for r in rows),
        "controls": rows,
    }


def _scrub(value: Any, key: str = "") -> Any:
    """Defence in depth: the excerpt holds names and settings, but a credential-looking value or a
    secret-named key is replaced rather than shipped."""
    if isinstance(value, dict):
        return {k: _scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, key) for v in value]
    if isinstance(value, str) and (secret_value(value) or (secret_key_name(key) and len(value) >= 20)):
        return REDACTED
    return value


def spec_excerpt(spec: Spec) -> dict[str, Any]:
    dump = spec.model_dump(mode="json")
    auth = dump.get("auth") or {}
    obs = dump.get("observability") or {}
    excerpt = {
        "regulated": dump.get("regulated"),
        "compliance": dump.get("compliance"),
        "roles": [r["name"] for r in auth.get("roles", [])],
        "permissions": [{"entity": p["entity"], "operation": p["operation"], "roles": p["roles"]}
                        for p in auth.get("permissions", [])],
        "history": [{"entity": h["entity"], "fields": h["fields"], "retention_days": h["retention_days"]}
                    for h in dump.get("history", [])],
        "observability": {"enabled": obs.get("enabled"), "extra_redact_keys": obs.get("extra_redact_keys", [])}
        if obs else None,
    }
    return _scrub(excerpt)  # type: ignore[no-any-return]


def _json(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def _mapping_md(summary: dict[str, Any], project_name: str) -> str:
    lines = [f"# Control mapping: {project_name}", "",
             f"Framework: {FRAMEWORK_LABELS.get(summary['framework'], summary['framework'])}", ""]
    for c in summary["controls"]:
        lines += [f"## {c['id']} {c['title']} [{c['status']}]", "", c["reason"], "", "Spec facts:"]
        lines += [f"- `{e['fact']}` = `{json.dumps(e['value'], sort_keys=True)}`" for e in c["evidence"]]
        lines += ["", "Proving tests:"]
        lines += [f"- {t['where']}: `{t['file']}::{t['name']}`" for t in c["tests"]]
        lines.append("")
    return "\n".join(lines)


def _tests_txt(summary: dict[str, Any]) -> str:
    seen: dict[tuple[str, str, str], None] = {}
    for c in summary["controls"]:
        for t in c["tests"]:
            seen[(t["where"], t["file"], t["name"])] = None
    gen = sorted(k for k in seen if k[0] == "generated")
    plat = sorted(k for k in seen if k[0] == "platform")
    out = ["Tests that prove the controls in this bundle.", "", "Generated project (run inside the project):"]
    out += [f"  {f}::{n}" for _, f, n in gen]
    out += ["", "  command: " + TEST_COMMAND.format(names=" or ".join(sorted({n for _, _, n in gen}))), "",
            "Builder platform repository:"]
    out += [f"  {f}::{n}" for _, f, n in plat]
    out += ["", "  command: uv run pytest -q " + " ".join(sorted({f"{f}::{n}" for _, f, n in plat})), ""]
    return "\n".join(out)


def _readme(project_name: str, framework: str, generated_at: str, summary: dict[str, Any]) -> str:
    return (
        f"# Evidence bundle: {project_name}\n\nFramework: {FRAMEWORK_LABELS.get(framework, framework)}\n"
        f"Generated at: {generated_at}\n\n"
        f"Controls: {summary['met']} met, {summary['unmet']} unmet, {summary['not_applicable']} not applicable.\n\n"
        "Files:\n- controls.json: every control, its status, reason, spec facts and tests\n"
        "- mapping.md: control -> spec facts -> proving tests, readable\n"
        "- spec-excerpt.json: the regulated and compliance blocks, roles and permissions (no secrets)\n"
        "- tests.txt: the proving tests and how to run them\n- MANIFEST.json: sha256 of every file\n\n"
        "This bundle is derived from the project's specification only. It maps controls to the behaviour "
        "the generated project is built and tested to have; it is not an audit opinion or a certification, "
        "and it says nothing about how the project is operated.\n"
    )


def evidence_bundle(spec: Spec, framework: str, project_name: str, generated_at: str) -> bytes:
    if framework not in FRAMEWORKS:
        _check_framework(framework)
    summary = controls_for(spec, framework)
    safe_name = re.sub(r"[^\w .-]", "_", project_name)[:120]
    files: dict[str, bytes] = {
        "controls.json": _json({"generated_at": generated_at, "project": safe_name, **summary}),
        "mapping.md": _mapping_md(summary, safe_name).encode(),
        "spec-excerpt.json": _json(spec_excerpt(spec)),
        "tests.txt": _tests_txt(summary).encode(),
        "README.md": _readme(safe_name, framework, generated_at, summary).encode(),
    }
    manifest = {"generated_at": generated_at, "framework": framework,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files["MANIFEST.json"] = _json(manifest)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


GENERATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def default_generated_at(spec: Spec) -> str:
    """Deterministic stamp when the caller gives none: derived from the spec, so the same spec gives the same bytes."""
    return f"spec-{spec_hash(spec)[:12]}"
