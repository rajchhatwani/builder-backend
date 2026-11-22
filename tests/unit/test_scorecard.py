"""CP-6E: scorecard checks, each pass and fail, fix actions, overall score."""

import json
from pathlib import Path
from typing import Any

from app.core.scorecard import ScorecardInput, compute_scorecard
from app.core.spec_models import Spec, SpecPermission

SPECS = Path(__file__).resolve().parents[1] / "fixtures" / "specs"
PID = "11111111-1111-1111-1111-111111111111"


def _spec(name: str = "authz_tenant", **changes: Any) -> Spec:
    d = json.loads((SPECS / f"{name}.json").read_text())
    d.update(changes)
    return Spec.model_validate(d)


def _card(spec: Spec, **kw: Any) -> dict[str, Any]:
    base = {
        "project_id": PID, "spec": spec, "validation_issues": 0, "latest_spec_hash": "h", "current_spec_hash": "h",
        "recorded_blocks": {"crud": "1.0.0"}, "current_blocks": {"crud": "1.0.0"},
        "base_tree": {"requirements.txt": "a==1\n"}, "regenerated_tree": {"requirements.txt": "a==1\n"},
    }
    base.update(kw)
    return compute_scorecard(ScorecardInput(**base))


def _by_id(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in card["checks"]}


def test_all_green_scorecard_passes() -> None:
    spec = _spec()
    assert spec.auth is not None and spec.auth.enabled
    card = _card(spec)
    statuses = {c["id"]: c["status"] for c in card["checks"]}
    assert all(v == "pass" for v in statuses.values()), statuses
    assert card["score"] == 100 and card["passing"] is True
    assert {c["group"] for c in card["checks"]} == {"security", "dependency_freshness", "hook_coverage", "block_version_lag", "drift"}
    assert all(c["fix"]["action"] == "none" and c["fix"]["route"] == "" for c in card["checks"])


def test_security_auth_disabled_fails() -> None:
    spec = _spec()
    assert spec.auth is not None
    spec.auth.enabled = False
    card = _card(spec)
    assert _by_id(card)["security.auth_enabled"]["status"] == "fail"
    assert card["passing"] is False and card["score"] < 100
    assert _card(_spec("minimal"))["checks"][0]["status"] == "fail"  # no auth block at all


def test_security_tenant_rules() -> None:
    spec = _spec()
    assert spec.auth is not None
    spec.auth.multi_tenant = True
    ent = spec.entities[0].name
    spec.auth.permissions = [SpecPermission(entity=ent, operation="list", roles=["admin"])]
    chk = _by_id(_card(spec))["security.tenant_rules"]
    assert chk["status"] == "fail" and ent in chk["detail"]
    spec.auth.permissions[0].row_rule = "tenant"
    assert _by_id(_card(spec))["security.tenant_rules"]["status"] == "pass"


def test_security_secret_in_spec_fails_and_names_are_not_values() -> None:
    spec = _spec()
    spec.settings = []
    dump = spec.model_dump(mode="json")
    assert _by_id(_card(spec))["security.no_secrets"]["status"] == "pass"
    spec2 = Spec.model_validate({**dump, "project": {**dump["project"], "description": "key AKIAABCDEFGHIJKLMNOP"}})
    assert _by_id(_card(spec2))["security.no_secrets"]["status"] == "fail"


def test_security_validation_issues_and_headers() -> None:
    spec = _spec()
    assert _by_id(_card(spec, validation_issues=3))["security.spec_valid"]["status"] == "fail"
    assert spec.auth is not None
    spec.auth.security_headers_enabled = False
    assert _by_id(_card(spec))["security.headers"]["status"] == "fail"


def test_dependency_freshness_warns_with_open_upgrade() -> None:
    card = _card(_spec(), regenerated_tree={"requirements.txt": "a==2\n"})
    chk = _by_id(card)["dependency_freshness"]
    assert chk["status"] == "warn" and "a" in chk["detail"]
    assert chk["fix"] == {"action": "open_upgrade", "route": f"/projects/{PID}/upgrades"}
    assert card["passing"] is True  # a warning does not fail the card


def test_dependency_freshness_without_generation() -> None:
    chk = _by_id(_card(_spec(), base_tree=None, regenerated_tree=None))["dependency_freshness"]
    assert chk["status"] == "warn" and chk["fix"]["action"] == "regenerate"


def test_block_version_lag() -> None:
    warn = _by_id(_card(_spec(), current_blocks={"crud": "1.1.0"}))["block_version_lag"]
    assert warn["status"] == "warn" and warn["fix"]["action"] == "open_upgrade"
    fail = _by_id(_card(_spec(), current_blocks={"crud": "2.0.0"}))["block_version_lag"]
    assert fail["status"] == "fail"
    none = _by_id(_card(_spec(), recorded_blocks=None))["block_version_lag"]
    assert none["status"] == "warn" and none["fix"]["action"] == "regenerate"


def test_hook_coverage_and_hook_drift() -> None:
    spec = _spec("hooks_invoice")
    names = [h.name for h in spec.hooks]
    assert names
    none = _card(spec, hook_entries=[])
    assert _by_id(none)["hook_coverage"]["status"] == "fail"
    assert _by_id(none)["hook_coverage"]["fix"]["action"] == "redeclare_hook"
    assert _by_id(none)["drift.hooks"]["status"] == "warn"
    unapproved = _card(spec, hook_entries=[{"hook_name": n, "approved_by": None} for n in names])
    assert _by_id(unapproved)["hook_coverage"]["status"] == "fail"
    assert _by_id(unapproved)["drift.hooks"]["status"] == "pass"
    full = _card(spec, hook_entries=[{"hook_name": n, "approved_by": "u"} for n in names])
    assert _by_id(full)["hook_coverage"]["status"] == "pass"
    if len(names) > 1:
        part = _card(spec, hook_entries=[{"hook_name": names[0], "approved_by": "u"}])
        assert _by_id(part)["hook_coverage"]["status"] == "warn"


def test_drift_spec_hash() -> None:
    chk = _by_id(_card(_spec(), latest_spec_hash="old"))["drift.spec"]
    assert chk["status"] == "warn" and chk["fix"] == {"action": "regenerate", "route": f"/projects/{PID}/generate/download"}
    never = _by_id(_card(_spec(), latest_spec_hash=None))["drift.spec"]
    assert never["status"] == "warn"
