"""CP-6C: control catalogue, statuses derived from the spec, test-name existence, evidence zip."""

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.core.compliance_controls import CONTROLS, FRAMEWORKS, GENERATED
from app.core.generator.engine import generate
from app.core.spec_models import Spec
from app.exceptions import AppError
from app.services.compliance_service import controls_for, evidence_bundle

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "tests" / "fixtures" / "specs"
STAMP = "2026-01-01T00:00:00Z"
SECRETS = ("sk_live_0123456789abcdefghij", "AKIAABCDEFGHIJKLMNOP")


def _spec_dict(**changes: Any) -> dict[str, Any]:
    d = json.loads((SPECS / "regulated_clients.json").read_text())
    d.update(changes)
    return d


def _spec(**changes: Any) -> Spec:
    return Spec.model_validate(_spec_dict(**changes))


def _status(spec: Spec, control_id: str) -> str:
    rows = {c["id"]: c for c in controls_for(spec)["controls"]}
    return str(rows[control_id]["status"])


def _names(files: dict[str, str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path, text in files.items():
        if path.startswith("tests/") and path.endswith(".py"):
            out[path] = set(re.findall(r"^(?:async )?def (test_\w+)", text, re.M))
    return out


def test_catalogue_shape() -> None:
    counts = {fw: sum(c.framework == fw for c in CONTROLS) for fw in FRAMEWORKS}
    assert counts["soc2"] >= 8 and counts["hipaa"] >= 6 and counts["pci"] >= 5
    assert len({c.id for c in CONTROLS}) == len(CONTROLS)
    for c in CONTROLS:
        assert c.title and c.description and len(c.tests) >= 1, c.id


def test_regulated_off_is_unmet_and_on_is_met() -> None:
    off = _spec(regulated={**_spec_dict()["regulated"], "enabled": False})
    on = _spec()
    for cid in ("SOC2-CC6.7", "HIPAA-164.312(a)(2)(iv)", "PCI-3.5"):
        assert _status(off, cid) == "unmet", cid
        assert _status(on, cid) == "met", cid
    assert _status(on, "SOC2-CC6.1-KEY") == "met"
    env = _spec(regulated={"enabled": True, "key_provider": "env", "fields": _spec_dict()["regulated"]["fields"]})
    assert _status(env, "PCI-3.6") == "unmet"


def test_summary_counts_and_framework_filter() -> None:
    s = controls_for(_spec(), "hipaa")
    assert s["framework"] == "hipaa"
    assert s["met"] + s["unmet"] + s["not_applicable"] == len(s["controls"]) >= 6
    assert {c["framework"] for c in s["controls"]} == {"hipaa"}
    assert len(controls_for(_spec())["controls"]) == len(CONTROLS)
    with pytest.raises(AppError) as err:
        controls_for(_spec(), "iso")
    assert err.value.code == "invalid_framework"


def test_not_applicable_when_no_personal_data() -> None:
    d = _spec_dict(regulated=None)
    d.pop("regulated")
    spec = Spec.model_validate(d)
    assert _status(spec, "SOC2-P2.1") == "not_applicable"
    assert _status(spec, "PCI-3.5") == "not_applicable"


def test_compliance_block_drives_retention_and_consent() -> None:
    base = _spec_dict()
    comp = {"enabled": True, "roles": ["admin"], "consent_purposes": ["care"], "export_consent_purpose": "care",
            "retention": [{"entity": "Order", "days": 90}]}
    try:
        spec = Spec.model_validate({**base, "compliance": comp})
    except Exception as exc:  # the schema must accept it even if validation rules are stricter
        pytest.fail(str(exc))
    assert _status(spec, "SOC2-CC6.5") == "met"
    assert _status(spec, "SOC2-P2.1") == "met"
    assert _status(_spec(), "SOC2-CC6.5") == "unmet"


def _platform_tests_exist() -> list[str]:
    missing = []
    for c in CONTROLS:
        for t in c.tests:
            if t.where == GENERATED:
                continue
            path = ROOT / t.file
            if not path.is_file() or not re.search(rf"def {re.escape(t.name)}\b", path.read_text()):
                missing.append(f"{t.file}::{t.name}")
    return missing


def test_every_platform_test_exists() -> None:
    assert _platform_tests_exist() == []


def test_every_generated_test_exists_in_a_generated_project() -> None:
    names: dict[str, set[str]] = {}
    specs = [Spec.model_validate(_spec_dict(observability={"enabled": True}))]
    clinic = SPECS / "regulated_clinic.json"
    assert clinic.is_file(), "the compliance test names can only be verified against the clinic fixture"
    specs.append(Spec.model_validate(json.loads(clinic.read_text())))
    for sp in specs:
        for path, found in _names(generate(sp)).items():
            names.setdefault(path, set()).update(found)
    missing = []
    for c in CONTROLS:
        for t in c.tests:
            if t.where != GENERATED:
                continue
            if t.name not in names.get(t.file, set()):
                missing.append(f"{t.file}::{t.name}")
    assert missing == []


def _zip(spec: Spec, fw: str = "hipaa") -> bytes:
    return evidence_bundle(spec, fw, "Clinic", STAMP)


def test_bundle_is_deterministic() -> None:
    assert _zip(_spec()) == _zip(_spec())
    assert _zip(_spec()) != _zip(_spec(), "pci")


def test_bundle_members_and_manifest_hashes() -> None:
    with zipfile.ZipFile(io.BytesIO(_zip(_spec()))) as zf:
        assert sorted(zf.namelist()) == ["MANIFEST.json", "README.md", "controls.json", "mapping.md",
                                         "spec-excerpt.json", "tests.txt"]
        assert all(i.date_time == (2020, 1, 1, 0, 0, 0) for i in zf.infolist())
        manifest = json.loads(zf.read("MANIFEST.json"))
        assert set(manifest["files"]) == set(zf.namelist()) - {"MANIFEST.json"}
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == digest
        controls = json.loads(zf.read("controls.json"))
        assert controls["controls"] and all(c["tests"] for c in controls["controls"])
        assert "test_a_tampered_ciphertext_is_refused" in zf.read("tests.txt").decode()
        assert "HIPAA-164.312(b)" in zf.read("mapping.md").decode()


def test_bundle_holds_no_secret_or_protected_value() -> None:
    d = _spec_dict()
    d["project"]["description"] = f"contact {SECRETS[0]}"
    d["regulated"]["fields"][0]["entity"] = "Customer"
    d["observability"] = {"enabled": True, "extra_redact_keys": ["ssn", SECRETS[1]]}
    spec = Spec.model_validate(d)
    with zipfile.ZipFile(io.BytesIO(_zip(spec))) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist()).decode()
    for secret in SECRETS:
        assert secret not in blob
    # a protected field is named (its name is not a value), never its content
    assert "api_token" in blob


def _clinic() -> Spec:
    return Spec.model_validate(json.loads((SPECS / "regulated_clinic.json").read_text()))


def test_clinic_spec_meets_the_compliance_controls() -> None:
    clinic = _clinic()
    for cid in ("SOC2-CC6.5", "HIPAA-164.312(a)(2)(ii)", "HIPAA-164.514(b)", "SOC2-P2.1"):
        assert _status(clinic, cid) == "met", cid


def test_export_that_keeps_an_identifier_is_not_met() -> None:
    d = _clinic().model_dump(mode="json")
    for f in d["compliance"]["export_fields"]:
        if f["field"] == "name":
            f["treatment"] = "keep"
    spec = Spec.model_validate(d)  # the schema accepts it; validation would refuse it
    rows = {c["id"]: c for c in controls_for(spec)["controls"]}
    assert rows["HIPAA-164.514(b)"]["status"] == "unmet"
    assert "Patient.name" in rows["HIPAA-164.514(b)"]["reason"]


def test_consent_without_anything_that_consults_it_is_not_met() -> None:
    d = _clinic().model_dump(mode="json")
    d["compliance"]["export_consent_purpose"] = None
    rows = {c["id"]: c for c in controls_for(Spec.model_validate(d))["controls"]}
    assert rows["SOC2-P2.1"]["status"] == "unmet"
