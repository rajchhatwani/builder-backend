"""CP-6C: the `compliance` spec block (retention + legal hold D42, consent D44, break-glass D45, de-identified
export D46): the good case, every refusal, the combination with `regulated`, and the generated files."""

import copy
import json
from pathlib import Path
from typing import Any

from app.core.generator.engine import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_compliance import is_direct_identifier

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _data() -> dict[str, Any]:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / "regulated_clinic.json").read_text(encoding="utf-8")))
    return data


def _codes(data: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(Spec.model_validate(data))}


def _block(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data["compliance"].update(changes)
    return data


def test_the_clinic_fixture_is_valid_and_combines_regulated_with_compliance() -> None:
    data = _data()
    assert data["regulated"]["enabled"] and data["compliance"]["enabled"]
    assert _codes(data) == set()


def test_compliance_without_regulated_is_valid_too() -> None:
    data = _data()
    data.pop("regulated")
    assert _codes(data) == set()


def test_enabled_needs_auth() -> None:
    data = _data()
    data.pop("auth")
    data.pop("regulated")
    assert ("compliance", "compliance_needs_auth") in _codes(data)


def test_enabled_needs_roles_and_they_must_exist() -> None:
    assert ("compliance.roles", "compliance_needs_roles") in _codes(_block(_data(), roles=[]))
    assert ("compliance.roles[0]", "unknown_role") in _codes(_block(_data(), roles=["ghost"]))


def test_a_disabled_block_needs_nothing() -> None:
    data = _data()
    data["compliance"] = {"enabled": False}
    assert _codes(data) == set()


def test_retention_entity_and_date_field() -> None:
    data = _data()
    data["compliance"]["retention"][0]["entity"] = "Nope"
    assert ("compliance.retention[0].entity", "unknown_entity") in _codes(data)
    data = _data()
    data["compliance"]["retention"][0]["date_field"] = "ghost"
    assert ("compliance.retention[0].date_field", "unknown_field") in _codes(data)
    data = _data()
    data["compliance"]["retention"][0]["date_field"] = "postcode"
    assert ("compliance.retention[0].date_field", "retention_bad_date_field") in _codes(data)
    data = _data()
    data["compliance"]["retention"][1]["date_field"] = "updated_at"  # the builtin timestamps are fine
    assert _codes(data) == set()


def test_retention_anonymise_fields() -> None:
    data = _data()
    data["compliance"]["retention"][0]["anonymise_fields"] = ["ghost"]
    assert ("compliance.retention[0].anonymise_fields[0]", "unknown_field") in _codes(data)
    data = _data()
    data["compliance"]["retention"][0]["anonymise_fields"] = []
    assert ("compliance.retention[0].anonymise_fields", "retention_anonymise_empty") in _codes(data)
    data = _data()
    data["entities"][1]["fields"][0]["required"] = True  # scheduled_at: a required datetime cannot be cleared
    data["compliance"]["retention"][0] = {"entity": "Appointment", "days": 400, "action": "anonymise", "anonymise_fields": ["scheduled_at"]}
    assert ("compliance.retention[0].anonymise_fields[0]", "retention_anonymise_type") in _codes(data)
    data = _data()  # a required TEXT field can be cleared (set to empty), an optional integer too
    data["entities"][0]["fields"][0]["required"] = True
    data["compliance"]["retention"][0]["anonymise_fields"] = ["age", "notes", "name"]
    assert _codes(data) == set()


def test_retention_rule_twice() -> None:
    data = _data()
    data["compliance"]["retention"].append(copy.deepcopy(data["compliance"]["retention"][1]))
    assert ("compliance.retention[3]", "duplicate_rule") in _codes(data)


def test_consent_purposes_are_unique_slugs() -> None:
    assert ("compliance.consent_purposes[2]", "duplicate_purpose") in _codes(
        _block(_data(), consent_purposes=["treatment", "research", "treatment"])
    )
    assert ("compliance.consent_purposes[0]", "invalid_purpose") in _codes(_block(_data(), consent_purposes=["Not A Slug"]))


def test_break_glass_needs_roles_that_exist() -> None:
    data = _data()
    data["compliance"]["break_glass"]["roles"] = []
    assert ("compliance.break_glass.roles", "break_glass_needs_roles") in _codes(data)
    data = _data()
    data["compliance"]["break_glass"]["roles"] = ["ghost"]
    assert ("compliance.break_glass.roles[0]", "unknown_role") in _codes(data)
    data = _data()
    data["compliance"]["break_glass"] = {"enabled": False}
    assert _codes(data) == set()


def test_export_entities_and_subject_field() -> None:
    data = _data()
    data["compliance"]["export_entities"][0]["entity"] = "Nope"
    assert ("compliance.export_entities[0].entity", "unknown_entity") in _codes(data)
    data = _data()
    data["compliance"]["export_entities"][0]["subject_field"] = "ghost"
    assert ("compliance.export_entities[0].subject_field", "unknown_field") in _codes(data)
    data = _data()
    data["compliance"]["export_entities"][0]["subject_field"] = None
    assert ("compliance.export_entities[0].subject_field", "export_needs_subject") in _codes(data)
    data = _data()  # a foreign key column is a valid subject
    data["compliance"]["export_entities"] = [{"entity": "Appointment", "subject_field": "patient_id"}]
    data["compliance"]["export_fields"] = []
    assert _codes(data) == set()


def test_export_fields_must_exist_and_be_listed() -> None:
    data = _data()
    data["compliance"]["export_fields"].append({"entity": "Nope", "field": "x", "treatment": "drop"})
    assert ("compliance.export_fields[7].entity", "unknown_entity") in _codes(data)
    data = _data()
    data["compliance"]["export_fields"].append({"entity": "Patient", "field": "ghost", "treatment": "drop"})
    assert ("compliance.export_fields[7].field", "unknown_field") in _codes(data)
    data = _data()
    data["compliance"]["export_fields"].append({"entity": "Appointment", "field": "status", "treatment": "keep"})
    assert ("compliance.export_fields[7].entity", "export_entity_not_listed") in _codes(data)


def test_keep_is_refused_on_a_direct_identifier() -> None:
    for field in ("name", "phone", "dob"):  # named like an identifier (and protected here)
        data = _data()
        data["compliance"]["export_fields"] = [{"entity": "Patient", "field": field, "treatment": "keep"}]
        assert ("compliance.export_fields[0].treatment", "export_keep_identifier") in _codes(data), field
    data = _data()
    data.pop("regulated")  # not protected, still named like an identifier
    data["compliance"]["export_fields"] = [{"entity": "Patient", "field": "phone", "treatment": "keep"}]
    assert ("compliance.export_fields[0].treatment", "export_keep_identifier") in _codes(data)
    data = _data()  # a non-identifier can be kept
    data["compliance"]["export_fields"] = [{"entity": "Patient", "field": "age", "treatment": "keep"}]
    assert _codes(data) == set()


def test_a_protected_field_can_only_be_hashed_or_dropped() -> None:
    data = _data()
    data["regulated"]["fields"].append({"entity": "Patient", "field": "postcode", "mode": "encrypt", "searchable": False})
    data["entities"][0]["options"]["filterable"] = []
    data["compliance"]["export_fields"] = [{"entity": "Patient", "field": "postcode", "treatment": "generalise"}]
    assert ("compliance.export_fields[0].treatment", "export_keep_identifier") in _codes(data)
    data["compliance"]["export_fields"] = [{"entity": "Patient", "field": "postcode", "treatment": "hash"}]
    assert _codes(data) == set()


def test_export_consent_purpose_must_be_declared() -> None:
    assert ("compliance.export_consent_purpose", "unknown_purpose") in _codes(_block(_data(), export_consent_purpose="marketing"))
    assert _codes(_block(_data(), export_consent_purpose=None)) == set()


def test_direct_identifier_rule() -> None:
    for name in ("email", "work_phone", "first_name", "ssn", "passport_no", "home_address", "dob"):
        assert is_direct_identifier(name, "string"), name
    assert is_direct_identifier("anything", "email") and is_direct_identifier("anything", "phone")
    assert not is_direct_identifier("age", "integer") and not is_direct_identifier("description", "string")
    assert not is_direct_identifier("tip", "string") and not is_direct_identifier("status", "string")


def test_the_identifier_rule_is_wide_enough() -> None:
    for name in ("date_of_birth", "birthdate", "DateOfBirth", "postcode", "zip", "zipCode", "postal_code", "mrn", "ip", "client_ip",
                 "latitude", "lat", "lng", "longitude", "insurance_no"):
        assert is_direct_identifier(name, "string"), name
    assert is_direct_identifier("born", "date") is False  # a plain date with an innocent name is the author's call
    assert is_direct_identifier("anything", "text")  # free text can hold anything


def test_keep_is_refused_on_birth_zip_mrn_ip_and_free_text() -> None:
    for name, type_ in (("date_of_birth", "date"), ("birthdate", "datetime"), ("zip_code", "string"), ("mrn", "string"),
                        ("client_ip", "string"), ("home_postcode", "string"), ("latitude", "float"), ("summary", "text")):
        data = _data()
        data["entities"][0]["fields"].append({"name": name, "type": type_, "required": False})
        data["compliance"]["export_fields"] = [{"entity": "Patient", "field": name, "treatment": "keep"}]
        assert ("compliance.export_fields[0].treatment", "export_keep_identifier") in _codes(data), name
        data["compliance"]["export_fields"][0]["treatment"] = "generalise"  # a transform is fine
        assert _codes(data) == set(), name


def test_the_block_generates_only_when_enabled() -> None:
    spec = Spec.model_validate(_data())
    files = generate(spec)
    for path in (
        "app/compliance/settings.py", "app/compliance/models.py", "app/compliance/service.py", "app/compliance/router.py",
        "app/compliance/purge.py", "alembic/versions/0044_compliance.py", "tests/test_compliance.py",
    ):
        assert path in files, path
    assert "app.compliance.router" in files["app/main.py"] and "_compliance_models" in files["app/models/__init__.py"]
    assert "COMPLIANCE_EXPORT_SALT" in files[".env.example"] and "COMPLIANCE_EXPORT_SALT" in files["docker-compose.yml"]
    assert "legal_holds" in files["tests/conftest.py"]
    data = _data()
    data["compliance"] = {"enabled": False}
    assert not [p for p in generate(Spec.model_validate(data)) if "compliance" in p]
    test_names = [line.split("(")[0][len("async def "):] for line in files["tests/test_compliance.py"].splitlines() if line.startswith("async def test_")]
    assert test_names == [
        "test_retention_purges_expired_rows", "test_purge_refuses_rows_under_legal_hold", "test_legal_hold_release_allows_purge",
        "test_consent_grant_and_withdraw", "test_break_glass_is_audited_and_time_boxed",
        "test_break_glass_denied_without_role_or_after_expiry", "test_export_has_no_direct_identifiers",
        "test_export_skips_subjects_without_consent", "test_hold_placed_mid_run_protects_the_row",
        "test_purge_does_not_cascade_into_held_children", "test_retention_removes_vault_tokens_of_cleared_rows",
        "test_tenant_scoping_of_holds_grants_and_audit", "test_unknown_or_foreign_grant_is_audited",
    ]


def test_the_settings_carry_the_spec_and_no_secret() -> None:
    files = generate(Spec.model_validate(_data()))
    text = files["app/compliance/settings.py"]
    assert "'compliance_officer'" in text and "'research'" in text and "'generalise'" in text
    assert "PROTECTED" in text and "'dob'" in text
    assert "salt" not in text.lower()
