"""Scenario tests for the generated `authz_pbac` project (Docs). Copied into the project's tests/
folder by tests/e2e/test_authz_stack.py and run against a real Postgres.

Roles: reader (default) <- editor <- manager (each inherits the one before).
Policies (see tests/fixtures/specs/authz_pbac.json):
  everyone: read_published (Document list/get/head when published), comment (own Comment rows),
            archived_is_frozen (deny update / replace / delete of archived documents)
  editor:   author (list/get/head/create/update own documents)
  manager:  manage (Document.*, unconditionally)
"""

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.main import app


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def doc(status: str = "draft", title: str = "d") -> dict:
    return {"title": title, "status": status}


async def make(http: AsyncClient, headers: dict, **kwargs) -> str:  # noqa: ANN003
    response = await http.post("/documents", json=doc(**kwargs), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_signed_out_is_refused(http: AsyncClient) -> None:
    assert (await http.get("/documents")).status_code == 401
    assert (await http.get("/comments")).status_code == 401


async def test_a_reader_sees_only_published_documents_and_cannot_write(http: AsyncClient) -> None:
    editor = await sign_in(http, "ed@example.com", roles=["editor"])
    reader = await sign_in(http, "rita@example.com", roles=["reader"])
    published = await make(http, editor, status="published")
    draft = await make(http, editor, status="draft")

    listing = (await http.get("/documents", headers=reader)).json()
    assert [d["id"] for d in listing["items"]] == [published] and listing["total"] == 1
    assert (await http.get(f"/documents/{published}", headers=reader)).status_code == 200
    assert (await http.get(f"/documents/{draft}", headers=reader)).status_code == 404
    # no policy carried by `reader` allows these at all: refused before any row is looked at
    assert (await http.post("/documents", json=doc(), headers=reader)).status_code == 403
    assert (
        await http.patch(f"/documents/{published}", json={"title": "x"}, headers=reader)
    ).status_code == 403
    assert (await http.delete(f"/documents/{published}", headers=reader)).status_code == 403


async def test_an_editor_works_on_own_documents_only(http: AsyncClient) -> None:
    ed = await sign_in(http, "ed@example.com", roles=["editor"])
    other = await sign_in(http, "other@example.com", roles=["editor"])
    mine = await make(http, ed, title="mine")
    theirs = await make(http, other, title="theirs")

    ids = {d["id"] for d in (await http.get("/documents", headers=ed)).json()["items"]}
    assert ids == {mine}  # drafts of others stay hidden
    assert (
        await http.patch(f"/documents/{mine}", json={"title": "edited"}, headers=ed)
    ).status_code == 200
    assert (
        await http.patch(f"/documents/{theirs}", json={"title": "hijack"}, headers=ed)
    ).status_code == 404
    assert (
        await http.delete(f"/documents/{mine}", headers=ed)
    ).status_code == 403  # editors cannot delete


async def test_publishing_your_own_document_keeps_it_readable(http: AsyncClient) -> None:
    ed = await sign_in(http, "ed@example.com", roles=["editor"])
    mine = await make(http, ed)
    assert (
        await http.patch(f"/documents/{mine}", json={"status": "published"}, headers=ed)
    ).status_code == 200
    reader = await sign_in(http, "rita@example.com", roles=["reader"])
    assert (await http.get(f"/documents/{mine}", headers=reader)).status_code == 200


async def test_archived_documents_are_frozen_for_everybody(http: AsyncClient) -> None:
    ed = await sign_in(http, "ed@example.com", roles=["editor"])
    boss = await sign_in(http, "boss@example.com", roles=["manager"])
    mine = await make(http, ed, status="archived")
    assert (
        await http.patch(f"/documents/{mine}", json={"title": "x"}, headers=ed)
    ).status_code == 404
    assert (
        await http.patch(f"/documents/{mine}", json={"title": "x"}, headers=boss)
    ).status_code == 404
    assert (await http.delete(f"/documents/{mine}", headers=boss)).status_code == 404
    # still readable by the manager (deny covers only update / replace / delete)
    assert (await http.get(f"/documents/{mine}", headers=boss)).status_code == 200


async def test_manager_inherits_editor_and_reader_and_sees_everything(http: AsyncClient) -> None:
    ed = await sign_in(http, "ed@example.com", roles=["editor"])
    boss = await sign_in(http, "boss@example.com", roles=["manager"])
    a = await make(http, ed, title="a")
    b = await make(http, boss, title="b")
    assert (await http.get("/documents", headers=boss)).json()["total"] == 2
    assert (
        await http.patch(f"/documents/{a}", json={"title": "reviewed"}, headers=boss)
    ).status_code == 200
    assert (await http.delete(f"/documents/{b}", headers=boss)).status_code == 204


async def test_comments_are_private_to_their_author(http: AsyncClient) -> None:
    rita = await sign_in(http, "rita@example.com", roles=["reader"])
    sam = await sign_in(http, "sam@example.com", roles=["reader"])
    created = await http.post("/comments", json={"body": "hello"}, headers=rita)
    assert created.status_code == 201, created.text
    assert (await http.get("/comments", headers=rita)).json()["total"] == 1
    assert (await http.get("/comments", headers=sam)).json()["total"] == 0
    assert (await http.get(f"/comments/{created.json()['id']}", headers=sam)).status_code == 404
    assert (await http.delete(f"/comments/{created.json()['id']}", headers=sam)).status_code == 404


async def test_a_caller_cannot_forge_the_creator(http: AsyncClient) -> None:
    ed = await sign_in(http, "ed@example.com", roles=["editor"])
    other = await sign_in(http, "other@example.com", roles=["editor"])
    me = (await http.post("/documents", json=doc(), headers=ed)).json()
    # created_by_id is stamped by the server; a client-supplied value is not part of the schema
    forged = await http.post(
        "/documents",
        json={**doc(), "created_by_id": "00000000-0000-0000-0000-000000000001"},
        headers=ed,
    )
    assert forged.status_code in (201, 422)
    listing = (await http.get("/documents", headers=other)).json()
    assert listing["total"] == 0
    assert me["id"]
