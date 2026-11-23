"""Cycle 6 demo with a NEUTRAL spec (no client project): a regulated clinic booking system with an evidence bundle.
Needs Docker (testcontainers Postgres).

One spec: Patient (name, date_of_birth, phone, diagnosis_note; all four encrypted, name searchable), the booking pack
(practitioner slots + rooms), roles admin / practitioner / receptionist, auth with tenants, a `compliance` block
(retention purge, consent purpose, break-glass, de-identified export) and the HIPAA control mapping.

Inside the generated project (tests/e2e/clinic_demo_scenarios.py, copied to tests/test_scenarios.py): ciphertext at
rest, no double booking, a legal hold stopping a purge, a time-boxed and audited break-glass read, a de-identified
export. Outside it (this file, no Docker needed): the spec validates, and the HIPAA evidence bundle is deterministic
for the spec hash and lists, for every control, a test that exists on disk or in the generated project."""

import copy
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from testcontainers.community.postgres import PostgresContainer

from app.core.compliance_controls import GENERATED
from app.core.generator import generate
from app.core.spec_models import Spec, spec_hash
from app.core.validation import validate
from app.services.compliance_service import default_generated_at, evidence_bundle
from tests.e2e.test_generated_project import ok, postgres, run  # noqa: F401

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "specs"
ROLES = ["admin", "practitioner", "receptionist"]


def _fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def clinic_spec() -> dict[str, Any]:
    base, booking = _fixture("regulated_clinic"), _fixture("booking_clinic")
    spec = copy.deepcopy(base)
    spec["project"] = {
        "name": "clinic_demo", "slug": "clinic-demo", "db_engine": "postgres",
        "description": "A neutral regulated clinic: encrypted patient data, booking without double booking, evidence bundle",
    }
    text = lambda n, t, m: {"name": n, "type": t, "required": n == "name", **({"max_length": m} if m else {})}  # noqa: E731
    spec["entities"] = [{
        "name": "Patient", "table_name": "patients", "plural_path": "patients",
        "options": {"sortable": ["created_at"], "filterable": []},
        "fields": [text("name", "string", 120), text("date_of_birth", "string", 20),
                   text("phone", "string", 30), text("diagnosis_note", "text", None), text("postcode", "string", 10)],
    }]
    spec["relations"] = []
    auth = spec["auth"]
    auth["roles"] = [{"name": "admin", "label": "Admin"}, {"name": "practitioner", "label": "Practitioner"},
                     {"name": "receptionist", "label": "Receptionist", "is_default": True}]
    auth["permissions"] = [
        {"entity": "Patient", "operation": op, "roles": roles, "row_rule": "tenant"}
        for op, roles in (("create", ROLES), ("list", ROLES), ("get", ROLES),
                          ("update", ["admin", "practitioner"]), ("delete", ["admin"]))
    ]
    spec["regulated"] = {
        "enabled": True, "key_provider": "file",
        "fields": [{"entity": "Patient", "field": f, "mode": "encrypt", "searchable": f == "name"}
                   for f in ("name", "date_of_birth", "phone", "diagnosis_note")],
    }
    comp = spec["compliance"]
    comp["roles"] = ["admin"]
    comp["retention"] = [{"entity": "Patient", "days": 3650, "date_field": "created_at", "action": "purge", "anonymise_fields": []}]
    comp["consent_purposes"] = ["treatment", "research"]
    comp["break_glass"] = {"enabled": True, "roles": ["practitioner"], "max_minutes": 60}
    comp["export_entities"] = [{"entity": "Patient", "subject_field": "id"}]
    comp["export_fields"] = [
        {"entity": "Patient", "field": "name", "treatment": "hash"},
        {"entity": "Patient", "field": "date_of_birth", "treatment": "drop"},
        {"entity": "Patient", "field": "phone", "treatment": "drop"},
        {"entity": "Patient", "field": "diagnosis_note", "treatment": "drop"},
        {"entity": "Patient", "field": "postcode", "treatment": "drop"},
        {"entity": "Patient", "field": "created_at", "treatment": "generalise"},
    ]
    spec["history"] = [{"entity": "Patient", "fields": ["postcode"], "retention_days": 365, "view_roles": ["admin"]}]
    comp["export_consent_purpose"] = "research"
    packs = copy.deepcopy(booking["packs"])
    packs["booking"]["kinds"] = [k for k in packs["booking"]["kinds"] if k["name"] in ("practitioner", "room")]
    for key in ("read_roles", "book_roles", "manage_roles"):
        packs["booking"][key] = ["admin", "practitioner", "receptionist"] if key != "manage_roles" else ["admin"]
    spec["packs"] = packs
    return spec


def test_the_clinic_spec_validates_with_no_issues() -> None:
    spec = Spec.model_validate(clinic_spec())
    assert validate(spec) == []


def _project_files(spec: Spec) -> dict[str, str]:
    files = dict(generate(spec))
    files["tests/test_scenarios.py"] = (HERE / "clinic_demo_scenarios.py").read_text(encoding="utf-8")
    return files


def test_the_clinic_stack_encrypts_books_holds_breaks_glass_and_exports(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = tmp_path_factory.mktemp("clinic_demo")
    for path, content in _project_files(Spec.model_validate(clinic_spec())).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/clinic_demo_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    print(output)
    assert "passed" in output and "failed" not in output


def test_the_hipaa_evidence_bundle_is_deterministic_and_every_control_lists_an_existing_test() -> None:
    spec = Spec.model_validate(clinic_spec())
    stamp = default_generated_at(spec)
    assert stamp == f"spec-{spec_hash(spec)[:12]}"
    first = evidence_bundle(spec, "hipaa", "Clinic Demo", stamp)
    assert first == evidence_bundle(Spec.model_validate(clinic_spec()), "hipaa", "Clinic Demo", stamp)  # same spec, same bytes
    changed = clinic_spec()
    changed["compliance"]["retention"][0]["days"] = 3000
    assert evidence_bundle(Spec.model_validate(changed), "hipaa", "Clinic Demo", stamp) != first  # the spec drives it

    with zipfile.ZipFile(io.BytesIO(first)) as zf:
        manifest = json.loads(zf.read("MANIFEST.json"))
        assert set(manifest["files"]) == set(zf.namelist()) - {"MANIFEST.json"}
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == digest
        controls = json.loads(zf.read("controls.json"))
    rows = controls["controls"]
    assert rows and {c["framework"] for c in rows} == {"hipaa"}
    assert {c["id"]: c["status"] for c in rows}["HIPAA-164.514(b)"] == "met"  # the de-identified export

    generated: dict[str, set[str]] = {}
    for path, text in generate(spec).items():
        if path.startswith("tests/") and path.endswith(".py"):
            generated[path] = set(re.findall(r"^(?:async )?def (test_\w+)", text, re.M))
    missing = []
    for row in rows:
        assert row["tests"], row["id"]  # every control lists at least one test
        for t in row["tests"]:
            if t["where"] == GENERATED:
                found = t["name"] in generated.get(t["file"], set())
            else:
                path = ROOT / t["file"]
                found = path.is_file() and re.search(rf"def {re.escape(t['name'])}\b", path.read_text(encoding="utf-8")) is not None
            if not found:
                missing.append(f"{row['id']}: {t['file']}::{t['name']}")
    assert missing == []
