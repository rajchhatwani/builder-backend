"""Scenario tests of the neutral clinic demo (copied into the generated `clinic_demo` project's tests/ by
tests/e2e/test_clinic_demo.py and run against a real Postgres). Reuses the compliance + booking scenario conventions.

Proves, with raw SQL against the real tables and the real routes: ciphertext at rest (`rg1:`), a second overlapping
booking of one resource is refused, a legal hold blocks a retention purge (the release lets it through), a break-glass
read is audited and stops working when its time box ends, and the de-identified export holds no direct identifier."""

import datetime as dt
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.db import session_factory
from tests._auth_support import authed_client, outbox  # noqa: F401

BERLIN = ZoneInfo("Europe/Berlin")
NAME = "Zxq Marker Patient"
DOB = "1980-02-03-ZXQ"
PHONE = "+0-ZXQ-555-0101"
DIAGNOSIS = "DIAGMARKER zxq asthma"


@pytest.fixture(autouse=True)
def _export_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPLIANCE_EXPORT_SALT", "scenario-salt-" + "y" * 24)


async def _raw(sql: str, **params: object) -> list[sa.Row]:
    async with session_factory() as session:
        return list((await session.execute(sa.text(sql), params)).all())


async def _exec(sql: str, **params: object) -> None:
    async with session_factory() as session:
        await session.execute(sa.text(sql), params)
        await session.commit()


async def _patient(client: AsyncClient) -> dict:
    response = await client.post(
        "/patients", json={"name": NAME, "date_of_birth": DOB, "phone": PHONE, "diagnosis_note": DIAGNOSIS}
    )
    assert response.status_code == 201, response.text
    created: dict = response.json()
    return created


def _monday() -> date:
    day = datetime.now(UTC).date() + timedelta(days=8)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day


def _at(day: date, hh: int, mm: int = 0) -> str:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=BERLIN).isoformat()


async def test_patient_data_is_ciphertext_at_rest(authed_client: AsyncClient) -> None:  # noqa: F811
    patient = await _patient(authed_client)
    assert patient["name"] == NAME and patient["phone"] == PHONE  # the authorised caller reads plaintext
    [row] = await _raw(
        "SELECT name, date_of_birth, phone, diagnosis_note FROM patients WHERE id = :i", i=uuid.UUID(patient["id"])
    )
    for stored, plain in zip(row, (NAME, DOB, PHONE, DIAGNOSIS), strict=True):
        assert stored.startswith("rg1:") and plain not in stored
    whole_table = json.dumps([list(map(str, r)) for r in await _raw("SELECT t::text FROM patients t")])
    for marker in (NAME, DOB, PHONE, DIAGNOSIS, "ZXQ", "zxq"):
        assert marker not in whole_table


async def test_a_second_overlapping_booking_of_the_same_resource_is_refused(authed_client: AsyncClient) -> None:  # noqa: F811
    doctor = await authed_client.post("/booking/resources", json={"kind": "practitioner", "name": "Dr. Demo"})
    assert doctor.status_code == 201, doctor.text
    rid, day = doctor.json()["id"], _monday()
    first = await authed_client.post("/booking/bookings", json={"resource_id": rid, "starts_at": _at(day, 9, 30), "confirm": True})
    assert first.status_code == 201, first.text
    second = await authed_client.post("/booking/bookings", json={"resource_id": rid, "starts_at": _at(day, 9, 30), "confirm": True})
    assert second.status_code == 409 and second.json()["code"] == "slot_taken", second.text
    other = await authed_client.post("/booking/bookings", json={"resource_id": rid, "starts_at": _at(day, 10, 0), "confirm": True})
    assert other.status_code == 201, other.text  # the next slot is still free
    held = await _raw("SELECT count(*) FROM bookings WHERE resource_id = :r AND status <> 'cancelled'", r=uuid.UUID(rid))
    assert held[0][0] == 2  # nothing extra was stored for the refused request


async def test_a_legal_hold_blocks_the_retention_purge(authed_client: AsyncClient) -> None:  # noqa: F811
    patient = await _patient(authed_client)
    pid = uuid.UUID(patient["id"])
    await _exec("UPDATE patients SET created_at = :t WHERE id = :i", t=datetime.now(UTC) - timedelta(days=3652), i=pid)
    hold = await authed_client.post("/compliance/legal-holds", json={"entity": "Patient", "record_id": patient["id"], "reason": "open claim"})
    assert hold.status_code == 201, hold.text
    held = await authed_client.post("/compliance/retention/run", json={})
    [purge] = [r for r in held.json()["rules"] if r["entity"] == "Patient" and r["action"] == "purge"]
    assert purge["held"] == 1 and purge["processed"] == 0
    assert (await _raw("SELECT count(*) FROM patients WHERE id = :i", i=pid))[0][0] == 1  # the hold kept the row

    assert (await authed_client.delete(f"/compliance/legal-holds/{hold.json()['id']}")).status_code == 200
    released = await authed_client.post("/compliance/retention/run", json={})
    [purge] = [r for r in released.json()["rules"] if r["entity"] == "Patient" and r["action"] == "purge"]
    assert purge["processed"] == 1 and purge["held"] == 0
    assert (await _raw("SELECT count(*) FROM patients WHERE id = :i", i=pid))[0][0] == 0


async def test_break_glass_read_is_audited_and_expires(authed_client: AsyncClient) -> None:  # noqa: F811
    patient = await _patient(authed_client)
    grant = await authed_client.post(
        "/compliance/break-glass", json={"reason": "emergency admission, need contact data", "entities": ["Patient"], "minutes": 5}
    )
    assert grant.status_code == 201, grant.text
    gid = grant.json()["id"]
    span = dt.datetime.fromisoformat(grant.json()["expires_at"]) - dt.datetime.fromisoformat(grant.json()["granted_at"])
    assert timedelta(minutes=4) < span <= timedelta(minutes=5, seconds=5)  # time-boxed to what was asked
    read = await authed_client.get(f"/compliance/break-glass/{gid}/records/Patient")
    assert read.status_code == 200, read.text
    [row] = [r for r in read.json() if r["id"] == patient["id"]]
    assert row["name"] == NAME and row["diagnosis_note"] == DIAGNOSIS  # decrypted for the emergency reader

    audit = (await authed_client.get("/compliance/audit", params={"action": "break_glass.read"})).json()
    assert len(audit) == 1 and audit[0]["entity"] == "Patient"
    assert NAME not in json.dumps(audit) and DIAGNOSIS not in json.dumps(audit)  # ids and counts, never values

    await _exec("UPDATE break_glass_grants SET expires_at = :t WHERE id = :g", t=datetime.now(UTC) - timedelta(seconds=1), g=uuid.UUID(gid))
    late = await authed_client.get(f"/compliance/break-glass/{gid}/records/Patient")
    assert late.status_code == 403, late.text  # the time box ended
    denied = (await authed_client.get("/compliance/audit", params={"action": "break_glass.denied"})).json()
    assert [d["detail"]["why"] for d in denied] == ["expired"]
    assert len((await authed_client.get("/compliance/audit", params={"action": "break_glass.read"})).json()) == 1  # no new read


async def test_the_de_identified_export_holds_no_direct_identifier(authed_client: AsyncClient) -> None:  # noqa: F811
    patient = await _patient(authed_client)
    none_yet = await authed_client.post("/compliance/exports", json={"entity": "Patient"})
    assert none_yet.json()["rows"] == [] and none_yet.json()["skipped_no_consent"] == 1  # no research consent yet
    consent = await authed_client.post("/compliance/consents", json={"subject": patient["id"], "purpose": "research"})
    assert consent.status_code == 201, consent.text
    exported = await authed_client.post("/compliance/exports", json={"entity": "Patient"})
    [item] = exported.json()["rows"]
    assert set(item) == {"pseudonym", "name", "created_at"}  # dob, phone and the diagnosis are dropped
    assert item["name"] != NAME and item["created_at"] == dt.datetime.now(dt.UTC).year  # hashed, generalised
    for marker in (NAME, DOB, PHONE, DIAGNOSIS, "ZXQ", "zxq", patient["id"]):
        assert marker not in exported.text
