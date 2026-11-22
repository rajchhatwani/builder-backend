"""Project scorecard (P4), pure. Inputs are plain data gathered by the service; every check carries a
fix action (`open_upgrade | regenerate | redeclare_hook | none`) and a route to do it."""

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.generator.base import FileTree
from app.core.spec_models import Spec
from app.core.upgrade_engine import block_changes, sbom_diff

_SECRET_KEY = re.compile(r"(password|secret|api_?key|private_?key|access_?key|credential)", re.I)
_SECRET_VALUE = re.compile(r"(sk_live_[0-9A-Za-z]{10,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
_POINTS = {"pass": 1.0, "warn": 0.5, "fail": 0.0}


@dataclass
class ScorecardInput:
    project_id: str
    spec: Spec
    validation_issues: int
    # None = the project was never generated
    latest_spec_hash: str | None = None
    current_spec_hash: str = ""
    recorded_blocks: dict[str, str] | None = None
    current_blocks: dict[str, str] = field(default_factory=dict)
    base_tree: FileTree | None = None
    regenerated_tree: FileTree | None = None
    hook_entries: list[dict[str, Any]] = field(default_factory=list)  # {hook_name, approved_by}


def _fix(action: str, project_id: str) -> dict[str, str]:
    routes = {
        "open_upgrade": f"/projects/{project_id}/upgrades",
        "regenerate": f"/projects/{project_id}/generate/download",
        "redeclare_hook": f"/projects/{project_id}/behavior/hooks",
        "none": "",
    }
    return {"action": action, "route": routes[action]}


def _check(cid: str, group: str, status: str, detail: str, fix: dict[str, str]) -> dict[str, Any]:
    return {"id": cid, "group": group, "status": status, "detail": detail, "fix": fix}


def _secret_paths(node: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and value and _SECRET_KEY.search(str(key)):
                found.append(here)
            else:
                found.extend(_secret_paths(value, here))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found.extend(_secret_paths(item, f"{path}[{i}]"))
    elif isinstance(node, str) and _SECRET_VALUE.search(node):
        found.append(path)
    return found


def _security(inp: ScorecardInput) -> list[dict[str, Any]]:
    pid, spec, auth = inp.project_id, inp.spec, inp.spec.auth
    none = _fix("none", pid)
    out = []
    if auth is not None and auth.enabled:
        out.append(_check("security.auth_enabled", "security", "pass", "authentication is on", none))
    else:
        out.append(_check("security.auth_enabled", "security", "fail", "the project has no authentication", none))
    if auth is not None and auth.multi_tenant:
        # An entity governed by explicit permissions must carry a tenant row rule on at least one of them;
        # entities with no permission rows are scoped by the other access models (abac/pbac/default).
        bare = [
            e.name
            for e in spec.entities
            if any(p.entity == e.name for p in auth.permissions)
            and not any(p.entity == e.name and p.row_rule == "tenant" for p in auth.permissions)
        ]
        if bare:
            out.append(_check("security.tenant_rules", "security", "fail",
                              f"multi-tenant entities without a tenant row rule: {', '.join(sorted(bare))}", none))
        else:
            out.append(_check("security.tenant_rules", "security", "pass", "no entity with explicit permissions lacks a tenant row rule", none))
    else:
        out.append(_check("security.tenant_rules", "security", "pass", "single-tenant project", none))
    leaks = _secret_paths(spec.model_dump(mode="json"))
    if leaks:
        out.append(_check("security.no_secrets", "security", "fail", f"secret-looking values in the spec: {', '.join(leaks[:5])}", none))
    else:
        out.append(_check("security.no_secrets", "security", "pass", "no secrets in the spec", none))
    if inp.validation_issues:
        out.append(_check("security.spec_valid", "security", "fail", f"the spec has {inp.validation_issues} validation issue(s)", none))
    else:
        out.append(_check("security.spec_valid", "security", "pass", "the spec validates", none))
    if auth is not None and auth.enabled and not auth.security_headers_enabled:
        out.append(_check("security.headers", "security", "fail", "security headers are switched off", none))
    elif auth is None or not auth.enabled:
        out.append(_check("security.headers", "security", "warn", "security headers come with the auth block, which is off", none))
    else:
        out.append(_check("security.headers", "security", "pass", "security headers are on", none))
    return out


def _freshness(inp: ScorecardInput) -> dict[str, Any]:
    pid = inp.project_id
    if inp.base_tree is None or inp.regenerated_tree is None:
        return _check("dependency_freshness", "dependency_freshness", "warn", "no generation to compare", _fix("regenerate", pid))
    diff = sbom_diff(inp.base_tree, inp.regenerated_tree)
    n = len(diff["added"]) + len(diff["removed"]) + len(diff["changed"])
    if n == 0:
        return _check("dependency_freshness", "dependency_freshness", "pass", "pins match the current generator", _fix("none", pid))
    names = [d["name"] for k in ("changed", "added", "removed") for d in diff[k]]
    return _check("dependency_freshness", "dependency_freshness", "warn",
                  f"{n} dependency pin(s) differ from the current generator: {', '.join(str(x) for x in names[:5])}",
                  _fix("open_upgrade", pid))


def _hook_coverage(inp: ScorecardInput) -> dict[str, Any]:
    pid, names = inp.project_id, [h.name for h in inp.spec.hooks]
    if not names:
        return _check("hook_coverage", "hook_coverage", "pass", "no hooks declared", _fix("none", pid))
    approved = {e["hook_name"] for e in inp.hook_entries if e.get("approved_by")}
    covered = [n for n in names if n in approved]
    if len(covered) == len(names):
        return _check("hook_coverage", "hook_coverage", "pass", f"all {len(names)} hook(s) approved in the ledger", _fix("none", pid))
    missing = sorted(set(names) - approved)
    status = "fail" if not covered else "warn"
    return _check("hook_coverage", "hook_coverage", status,
                  f"{len(covered)}/{len(names)} hook(s) approved; not approved: {', '.join(missing[:5])}",
                  _fix("redeclare_hook", pid))


def _lag(inp: ScorecardInput) -> dict[str, Any]:
    pid = inp.project_id
    if inp.recorded_blocks is None:
        return _check("block_version_lag", "block_version_lag", "warn", "no generation recorded block versions", _fix("regenerate", pid))
    changes = block_changes(inp.recorded_blocks, inp.current_blocks)
    if not changes:
        return _check("block_version_lag", "block_version_lag", "pass", "all blocks are at the current version", _fix("none", pid))
    status = "fail" if any(c["bump"] == "major" for c in changes) else "warn"
    return _check("block_version_lag", "block_version_lag", status,
                  f"{len(changes)} block(s) behind: " + ", ".join(f"{c['block']} {c['from']}->{c['to']}" for c in changes[:5]),
                  _fix("open_upgrade", pid))


def _drift(inp: ScorecardInput) -> list[dict[str, Any]]:
    pid = inp.project_id
    if inp.latest_spec_hash is None:
        spec_check = _check("drift.spec", "drift", "warn", "the project was never exported", _fix("regenerate", pid))
    elif inp.latest_spec_hash != inp.current_spec_hash:
        spec_check = _check("drift.spec", "drift", "warn", "the spec changed since the last export", _fix("regenerate", pid))
    else:
        spec_check = _check("drift.spec", "drift", "pass", "the spec matches the last export", _fix("none", pid))
    ledger = {e["hook_name"] for e in inp.hook_entries}
    unledgered = sorted(h.name for h in inp.spec.hooks if h.name not in ledger)
    if unledgered:
        hook_check = _check("drift.hooks", "drift", "warn", f"hooks in the spec with no ledger entry: {', '.join(unledgered[:5])}", _fix("redeclare_hook", pid))
    else:
        hook_check = _check("drift.hooks", "drift", "pass", "every spec hook has a ledger entry", _fix("none", pid))
    return [spec_check, hook_check]


def compute_scorecard(inp: ScorecardInput) -> dict[str, Any]:
    checks = [*_security(inp), _freshness(inp), _hook_coverage(inp), _lag(inp), *_drift(inp)]
    score = round(100 * sum(_POINTS[c["status"]] for c in checks) / len(checks))
    return {
        "score": score,
        "passing": not any(c["status"] == "fail" for c in checks),
        "checks": checks,
    }
