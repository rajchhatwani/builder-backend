"""Scenario tests for compliance on top of regulated mode (copied into the generated `regulated_clinic` project's tests/
by tests/e2e/test_compliance_stack.py and run against a real Postgres).

Spec: Patient.name / dob / phone are encrypted; retention anonymises Patient.phone + notes after 3650 days and purges
Appointments after 730; purposes treatment + research; break-glass for clinician_lead; export hashes name, generalises
postcode / age / created_at, drops the rest, and only exports subjects who consented to research.

Proves, with raw SQL against the real tables: a legal hold stops the anonymisation, the release lets it through and leaves
the protected columns encrypted, and a unique marker value is in NO compliance table (audit, grants, holds, consents,
runs) after a break-glass read, an export and a retention run."""

import datetime as dt
import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.db import session_factory
from tests._auth_support import authed_client, outbox  # noqa: F401

NAME = "Zxq Marker Patient"
DOB = "1980-02-03-ZXQ"
PHONE = "+0-ZXQ-555-0101"
NOTES = "NOTESMARKER zxq allergy"

@pytest.fixture(autouse=True)
def _export_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPLIANCE_EXPORT_SALT", "scenario-salt-" + "y" * 24)


TABLES = ("legal_holds", "consents", "break_glass_grants", "compliance_audit", "retention_runs")


async def _raw(sql: str, **params: object) -> list[sa.Row]:
    async with session_factory() as session:
        return list((await session.execute(sa.text(sql), params)).all())


async def _compliance_dump() -> str:
    parts = []
    for table in TABLES:
        parts.append(json.dumps([list(map(str, r)) for r in await _raw(f"SELECT * FROM {table}")]))  # noqa: S608
    return "\n".join(parts)


async def _patient(client: AsyncClient) -> dict:
    response = await client.post("/patients", json={"name": NAME, "dob": DOB, "phone": PHONE, "notes": NOTES, "postcode": "AB12", "age": 47})
    assert response.status_code == 201, response.text
    created: dict = response.json()
    return created


async def _age(patient_id: str, days: int) -> None:
    async with session_factory() as session:
        await session.execute(
            sa.text("UPDATE patients SET created_at = :t WHERE id = :i"),
            {"t": dt.datetime.now(dt.UTC) - dt.timedelta(days=days), "i": uuid.UUID(patient_id)},
        )
        await session.commit()


async def test_hold_then_release_anonymises_and_the_audit_never_holds_a_value(authed_client: AsyncClient) -> None:  # noqa: F811
    patient = await _patient(authed_client)
    [(name, dob, phone)] = await _raw("SELECT name, dob, phone FROM patients WHERE id = :i", i=uuid.UUID(patient["id"]))
    assert all(v.startswith("rg1:") for v in (name, dob, phone))  # protected at rest
    await _age(patient["id"], 3652)

    hold = await authed_client.post(
        "/compliance/legal-holds", json={"entity": "Patient", "record_id": patient["id"], "reason": "open claim"}
    )
    assert hold.status_code == 201, hold.text
    run = await authed_client.post("/compliance/retention/run", json={})
    assert run.status_code == 200, run.text
    [anonymise] = [r for r in run.json()["rules"] if r["entity"] == "Patient" and r["action"] == "anonymise"]
    assert anonymise["held"] == 1 and anonymise["processed"] == 0
    [(phone,)] = await _raw("SELECT phone FROM patients WHERE id = :i", i=uuid.UUID(patient["id"]))
    assert phone is not None  # the hold kept the row intact

    assert (await authed_client.delete(f"/compliance/legal-holds/{hold.json()['id']}")).status_code == 200
    run = await authed_client.post("/compliance/retention/run", json={})
    [anonymise] = [r for r in run.json()["rules"] if r["entity"] == "Patient" and r["action"] == "anonymise"]
    assert anonymise["processed"] == 1 and anonymise["held"] == 0
    [(name, dob, phone, notes)] = await _raw("SELECT name, dob, phone, notes FROM patients WHERE id = :i", i=uuid.UUID(patient["id"]))
    assert phone is None and notes is None  # cleared
    assert name.startswith("rg1:") and dob.startswith("rg1:")  # the rest stays encrypted
    again = await authed_client.post("/compliance/retention/run", json={})
    [anonymise] = [r for r in again.json()["rules"] if r["entity"] == "Patient" and r["action"] == "anonymise"]
    assert anonymise["matched"] == 0  # nothing left to clear: idempotent

    dump = await _compliance_dump()
    for marker in (NAME, DOB, PHONE, NOTES, "ZXQ", "zxq"):
        assert marker not in dump


async def test_break_glass_and_export_leave_no_value_in_the_compliance_tables(authed_client: AsyncClient) -> None:  # noqa: F811
    patient = await _patient(authed_client)
    grant = await authed_client.post(
        "/compliance/break-glass", json={"reason": "emergency admission, need contact data", "entities": ["Patient"], "minutes": 10}
    )
    assert grant.status_code == 201, grant.text
    read = await authed_client.get(f"/compliance/break-glass/{grant.json()['id']}/records/Patient")
    assert read.status_code == 200, read.text
    [row] = [r for r in read.json() if r["id"] == patient["id"]]
    assert row["name"] == NAME and row["phone"] == PHONE and "name_bidx" not in row  # decrypted for the emergency reader

    none_yet = await authed_client.post("/compliance/exports", json={"entity": "Patient"})
    assert none_yet.json()["rows"] == [] and none_yet.json()["skipped_no_consent"] == 1  # no research consent yet
    consent = await authed_client.post("/compliance/consents", json={"subject": patient["id"], "purpose": "research"})
    assert consent.status_code == 201
    exported = await authed_client.post("/compliance/exports", json={"entity": "Patient"})
    [item] = exported.json()["rows"]
    assert set(item) == {"pseudonym", "name", "postcode", "age", "created_at"}
    assert item["postcode"] == "A" and item["age"] == 40 and item["created_at"] == dt.datetime.now(dt.UTC).year
    for marker in (NAME, DOB, PHONE, NOTES, patient["id"]):
        assert marker not in exported.text

    dump = await _compliance_dump()
    for marker in (NAME, DOB, PHONE, NOTES, "ZXQ", "zxq"):
        assert marker not in dump
    assert patient["id"] in dump  # ids are what the audit keeps
