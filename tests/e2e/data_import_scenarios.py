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


async def test_m1_imported_rows_run_the_create_hooks(http, people, monkeypatch) -> None:  # noqa: ANN001
    """after_save (inside the transaction) and after_commit run once per created row, with the stored item."""
    from app.crud.tickets import TicketRepository

    calls: list[tuple[str, str, bool]] = []

    async def after_save(ctx) -> None:  # noqa: ANN001
        async with session_factory() as other:  # a second connection: the row is not visible before commit
            visible = (await other.execute(sa.text("select count(*) from tickets"))).scalar_one()
        calls.append(("after_save", ctx.item.title, visible == 0))

    async def after_commit(ctx) -> None:  # noqa: ANN001
        calls.append(("after_commit", ctx.item.title, True))

    hooks = {
        stage: (*TicketRepository.hooks.get(stage, ()), fn)
        for stage, fn in (("after_save", after_save), ("after_commit", after_commit))
    }
    monkeypatch.setattr(TicketRepository, "hooks", {**TicketRepository.hooks, **hooks})
    result = await upload(http, people["c1"], "title\nHooked one\nHooked two\n")
    assert result["counts"]["created"] == 2
    assert sorted(calls) == [
        ("after_commit", "Hooked one", True),
        ("after_commit", "Hooked two", True),
        ("after_save", "Hooked one", True),
        ("after_save", "Hooked two", True),
    ]
    dry = await upload(http, people["c1"], "title\nNever written\n", dry_run="true")
    assert dry["would_create"] == 1 and len(calls) == 4  # a dry run runs no after_* hook


async def test_m1_a_failing_after_save_hook_rolls_the_whole_import_back(http, people, monkeypatch) -> None:  # noqa: ANN001
    from app.crud.tickets import TicketRepository

    async def boom(ctx) -> None:  # noqa: ANN001
        raise RuntimeError("no")

    monkeypatch.setattr(
        TicketRepository, "hooks", {**TicketRepository.hooks, "after_save": (*TicketRepository.hooks.get("after_save", ()), boom)}
    )
    response = await http.post(
        "/tickets/import", files={"file": ("t.csv", b"title\nA\nB\n", "text/csv")}, headers=people["c1"]
    )
    assert response.status_code == 500 and response.json()["code"] == "hook_failed"
    monkeypatch.undo()
    assert await titles(http, people["c1"]) == []


async def test_m2_dedupe_is_exact_beyond_any_scan_cap(http, people, monkeypatch) -> None:  # noqa: ANN001
    """The existing-row check looks the file's keys up (IN queries per chunk): with a tiny chunk and many rows the
    re-upload is still fully idempotent, and rows outside the file are never loaded."""
    from app.imports import service

    monkeypatch.setattr(service, "PROBE_CHUNK", 3)
    body = "title\n" + "".join(f"Row {i}\n" for i in range(10))
    first = await upload(http, people["c1"], body)
    assert first["counts"]["created"] == 10
    again = await upload(http, people["c1"], body + "Extra\n")
    assert again["counts"] == {"total": 11, "created": 1, "duplicate": 10, "rejected": 0}
    other = await upload(http, people["admin"], body)  # another owner's scope: not a duplicate
    assert other["counts"]["created"] == 10
    monkeypatch.setattr(service, "MAX_PROBE_ROWS", 2)  # a probe that would be cut off refuses, never truncates
    response = await http.post(
        "/tickets/import", files={"file": ("t.csv", body.encode(), "text/csv")}, headers=people["c1"]
    )
    assert response.status_code == 422 and response.json()["code"] == "import_dedupe_too_large"


async def test_l4_dry_run_counts_only_rows_the_real_import_accepts(http, people, monkeypatch) -> None:  # noqa: ANN001
    from app.core.errors import AppError
    from app.crud.tickets import TicketRepository

    async def refuse_blocked(ctx) -> None:  # noqa: ANN001
        if ctx.values.get("title") == "Blocked":
            raise AppError("blocked_title", "this title is not allowed", 422)

    monkeypatch.setattr(
        TicketRepository,
        "hooks",
        {**TicketRepository.hooks, "before_save": (*TicketRepository.hooks.get("before_save", ()), refuse_blocked)},
    )
    text = "title\nFine\nBlocked\n"
    dry = await upload(http, people["c1"], text, dry_run="true")
    real = await upload(http, people["c1"], text)
    assert dry["would_create"] == 1 and dry["counts"]["rejected"] == 1
    assert (real["counts"]["created"], real["counts"]["rejected"]) == (1, 1)
    assert dry["rejected_rows"][0]["errors"][0]["code"] == "blocked_title"


async def test_l8_an_oversized_body_is_refused_before_the_file_is_read(http, people) -> None:  # noqa: ANN001
    big = b"title\n" + b"x" * (6 * 1024 * 1024)
    declared = await http.post(
        "/tickets/import", files={"file": ("t.csv", big, "text/csv")}, headers=people["c1"]
    )
    assert declared.status_code == 413 and declared.json()["code"] == "import_too_large"

    boundary = "xxBOUNDARYxx"
    chunk = b"y" * 65536

    async def stream():  # chunked: no Content-Length, so only the streamed byte count can stop it
        yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="t.csv"\r\n\r\ntitle\n'.encode()
        for _ in range(100):
            yield chunk
        yield f"\r\n--{boundary}--\r\n".encode()

    chunked = await http.post(
        "/tickets/import",
        content=stream(),
        headers={**people["c1"], "content-type": f"multipart/form-data; boundary={boundary}"},
    )
    assert chunked.status_code == 413 and chunked.json()["code"] == "import_too_large"
    assert await titles(http, people["c1"]) == []

