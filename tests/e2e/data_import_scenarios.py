"""Scenario tests for CSV import / export in the generated `search` project (copied into the project's tests/
by tests/e2e/test_data_import_stack.py, run against a real Postgres).

Ticket: owner-scoped for customers (admin sees every ticket), title required, internal_note readable and
writable by admin only. Customers and admin may create; admin and customers may list.
"""

import csv
import io
import json

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.db import session_factory
from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401

THREE = "title\nAlpha\nBeta\n" + "x" * 121 + "\n"  # row 3: title longer than max_length 120


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "c1": await sign_in(http, "c1@example.com", roles=["customer"], n=0),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=1),
    }


async def upload(http: AsyncClient, who: dict[str, str], text: str, **params: object) -> dict:
    response = await http.post(
        "/tickets/import", files={"file": ("t.csv", text.encode(), "text/csv")}, params=params, headers=who
    )
    assert response.status_code == 200, response.text
    return response.json()


async def titles(http: AsyncClient, who: dict[str, str]) -> list[str]:
    response = await http.get("/tickets", params={"limit": 100}, headers=who)
    assert response.status_code == 200, response.text
    return sorted(i["title"] for i in response.json()["items"])


async def test_import_creates_rows_and_rejects_the_bad_one(http, people) -> None:  # noqa: ANN001
    result = await upload(http, people["c1"], THREE)
    assert result["counts"] == {"total": 3, "created": 2, "duplicate": 0, "rejected": 1}
    assert result["rejected_rows"][0]["row"] == 3
    assert result["rejected_rows"][0]["errors"][0]["code"] == "too_long"
    assert await titles(http, people["c1"]) == ["Alpha", "Beta"]  # really in the generated table


async def test_reupload_is_idempotent_and_in_file_repeats_are_duplicates(http, people) -> None:  # noqa: ANN001
    await upload(http, people["c1"], THREE)
    again = await upload(http, people["c1"], THREE)
    assert again["counts"] == {"total": 3, "created": 0, "duplicate": 2, "rejected": 1}
    repeated = await upload(http, people["c1"], "title\nGamma\nGamma\n")
    assert repeated["counts"] == {"total": 2, "created": 1, "duplicate": 1, "rejected": 0}
    assert await titles(http, people["c1"]) == ["Alpha", "Beta", "Gamma"]


async def test_dry_run_writes_nothing(http, people) -> None:  # noqa: ANN001
    result = await upload(http, people["c1"], THREE, dry_run="true")
    assert result["dry_run"] is True and result["counts"]["created"] == 0 and result["would_create"] == 2
    assert await titles(http, people["c1"]) == []
    assert (await upload(http, people["c1"], THREE))["counts"]["created"] == 2


async def test_a_field_the_caller_may_not_write_is_rejected_and_never_stored(http, people) -> None:  # noqa: ANN001
    text = "title,internal_note\nSecret one,leak-me\nPlain,\n"
    result = await upload(http, people["c1"], text)
    assert result["counts"] == {"total": 2, "created": 1, "duplicate": 0, "rejected": 1}
    row = result["rejected_rows"][0]
    assert row["errors"][0] == {
        "field": "internal_note",
        "code": "field_not_writable",
        "message": "you may not set this field",
    }
    assert "internal_note" not in row["values"] and "leak-me" not in json.dumps(result)  # no echo of hidden columns
    async with session_factory() as session:
        stored = (await session.execute(sa.text("select title, internal_note from tickets"))).all()
    assert [tuple(r) for r in stored] == [("Plain", None)]
    admin = await upload(http, people["admin"], text)  # the admin may write it
    assert admin["counts"]["created"] == 2 and admin["counts"]["rejected"] == 0


async def test_export_neutralizes_formulas_and_hides_unreadable_columns(http, people) -> None:  # noqa: ANN001
    await upload(http, people["admin"], 'title,internal_note\n"=HYPERLINK(""x"")",vip-note\n')
    admin = await http.get("/tickets/export.csv", headers=people["admin"])
    assert admin.status_code == 200 and admin.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(admin.text)))
    assert rows[0]["title"] == "'=HYPERLINK(\"x\")" and rows[0]["internal_note"] == "vip-note"
    mine = await upload(http, people["c1"], 'title\n"=HYPERLINK(""x"")"\n')
    assert mine["counts"]["created"] == 1
    customer = await http.get("/tickets/export.csv", headers=people["c1"])
    assert customer.status_code == 200
    reader = csv.DictReader(io.StringIO(customer.text))
    assert reader.fieldnames is not None and "internal_note" not in reader.fieldnames
    assert [r["title"] for r in reader] == ["'=HYPERLINK(\"x\")"]  # own rows only
    assert "vip-note" not in customer.text and "X-Export-Truncated" not in customer.headers


async def test_bad_files_and_access(http, people) -> None:  # noqa: ANN001
    response = await http.post(
        "/tickets/import", files={"file": ("t.csv", b"\xff\xfe\x00")}, headers=people["c1"]
    )
    assert response.status_code == 422 and response.json()["code"] == "import_bad_csv"
    anonymous = await http.post("/tickets/import", files={"file": ("t.csv", b"title\nx\n")})
    assert anonymous.status_code in (401, 403)
