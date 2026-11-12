"""Scenario tests for the generated `search` project against a REAL OpenSearch (copied into the project's
tests/ by tests/e2e/test_search_opensearch_stack.py; SEARCH_OS_URL points at the container).

Same fixture rows as search_scenarios.py. The adapter swap must give exactly the FTS filtered set."""

import json
import os
import urllib.request

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.db import session_factory
from app.main import app
from app.search import reindex as reindex_cli
from tests._auth_support import outbox, sign_in  # noqa: F401

URL = os.environ["SEARCH_OS_URL"]


def refresh() -> None:
    """OpenSearch is near-real-time: make every write visible before asserting."""
    request = urllib.request.Request(URL + "/_refresh", method="POST")  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        assert response.status == 200


def raw_index(path: str, body: dict, method: str = "PUT") -> None:
    request = urllib.request.Request(  # noqa: S310
        URL + path, data=json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30):  # noqa: S310
        pass


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def make(http: AsyncClient, who: dict[str, str], title: str) -> str:
    response = await http.post("/tickets", json={"title": title}, headers=who)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def search(http: AsyncClient, who: dict[str, str], q: str) -> dict:
    response = await http.get("/tickets/search", params={"q": q}, headers=who)
    assert response.status_code == 200, response.text
    return response.json()


async def test_real_opensearch_returns_the_same_filtered_set_as_fts(http, monkeypatch) -> None:  # noqa: ANN001
    people = {
        "c1": await sign_in(http, "c1@example.com", roles=["customer"], n=0),
        "c2": await sign_in(http, "c2@example.com", roles=["customer"], n=1),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=2),
    }
    mine = await make(http, people["c1"], "Printer broken")
    other = await make(http, people["c2"], "Printer jammed")
    async with session_factory() as session:
        await session.execute(
            sa.text("update tickets set internal_note = 'vipescalation' where id = cast(:i as uuid)"), {"i": mine}
        )
        await session.commit()
    queries = [("c1", "printer"), ("c2", "printer"), ("admin", "printer"), ("c1", "vipescalation"), ("admin", "vipescalation"), ("c2", "vipescalation")]
    fts = {(w, q): await search(http, people[w], q) for w, q in queries}
    assert fts[("admin", "printer")]["total"] == 2 and fts[("c1", "vipescalation")]["total"] == 0

    monkeypatch.setenv("SEARCH_BACKEND", "opensearch")
    monkeypatch.setenv("SEARCH_OPENSEARCH_URL", URL)
    monkeypatch.setenv("SEARCH_OPENSEARCH_INDEX_PREFIX", "scn-")
    assert await reindex_cli.reindex() == {"Ticket": 2}
    refresh()
    for who, q in queries:
        got = await search(http, people[who], q)
        assert sorted(i["id"] for i in got["items"]) == sorted(i["id"] for i in fts[(who, q)]["items"]), (who, q)
        assert got["total"] == fts[(who, q)]["total"], (who, q)
        if who != "admin":
            assert all("internal_note" not in i for i in got["items"]), (who, q)

    # write-through: a new row and a delete reach the real index
    third = await make(http, people["c1"], "Printer smoking")
    refresh()
    assert (await search(http, people["c1"], "printer"))["total"] == 2
    assert (await http.delete(f"/tickets/{third}", headers=people["c1"])).status_code == 204
    refresh()
    assert [i["id"] for i in (await search(http, people["c1"], "printer"))["items"]] == [mine]

    # a stale or hostile index (rows the caller may not read, a ghost, junk id) cannot widen access
    raw_index(f"/scn-ticket/_doc/{other}", {"title": "Printer jammed", "internal_note": "vipescalation"})
    raw_index("/scn-ticket/_doc/00000000-0000-4000-8000-0000000000ff", {"title": "Printer ghost"})
    raw_index("/scn-ticket/_doc/not-a-uuid", {"title": "Printer junk"})
    refresh()
    c1 = await search(http, people["c1"], "printer")
    assert [i["id"] for i in c1["items"]] == [mine] and c1["total"] == 1
    assert (await search(http, people["c1"], "vipescalation"))["total"] == 0
    admin = await search(http, people["admin"], "printer")
    assert sorted(i["id"] for i in admin["items"]) == sorted([mine, other])
