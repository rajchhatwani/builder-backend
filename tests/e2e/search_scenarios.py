"""Scenario tests for the generated `search` project (copied into the project's tests/ by
tests/e2e/test_search_stack.py, run against a real Postgres).

Ticket: owner-scoped for customers (admin sees every ticket, role_scoped), soft delete, searchable
title + internal_note, internal_note readable and writable by admin only.
"""

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.db import session_factory
from app.main import app
from app.search import config as search_config
from app.search import reindex as reindex_cli
from app.search.adapters import fake_engine
from tests._auth_support import outbox, sign_in  # noqa: F401


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "c1": await sign_in(http, "c1@example.com", roles=["customer"], n=0),
        "c2": await sign_in(http, "c2@example.com", roles=["customer"], n=1),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=2),
    }


async def make(http: AsyncClient, who: dict[str, str], title: str) -> str:
    response = await http.post("/tickets", json={"title": title}, headers=who)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def set_note(ticket_id: str, note: str) -> None:
    async with session_factory() as session:
        await session.execute(
            sa.text("update tickets set internal_note = :n where id = cast(:i as uuid)"),
            {"n": note, "i": ticket_id},
        )
        await session.commit()


async def search(http: AsyncClient, who: dict[str, str], q: str, **params: object) -> dict:
    response = await http.get("/tickets/search", params={"q": q, **params}, headers=who)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def world(http, people):  # noqa: ANN001
    mine = await make(http, people["c1"], "Printer broken")
    other = await make(http, people["c2"], "Printer jammed")
    await set_note(mine, "vipescalation")
    return {"mine": mine, "other": other}


async def test_row_scope_decides_hits_and_total(http, people, world) -> None:  # noqa: ANN001
    own = await search(http, people["c1"], "printer")
    assert own["total"] == 1 and [i["id"] for i in own["items"]] == [world["mine"]]
    everyone = await search(http, people["admin"], "printer")
    assert everyone["total"] == 2
    assert {i["id"] for i in everyone["items"]} == {world["mine"], world["other"]}


async def test_hidden_field_is_not_searched_nor_returned(http, people, world) -> None:  # noqa: ANN001
    assert (await search(http, people["c1"], "vipescalation"))["total"] == 0
    admin = await search(http, people["admin"], "vipescalation")
    assert admin["total"] == 1 and admin["items"][0]["internal_note"] == "vipescalation"
    hit = (await search(http, people["c1"], "printer"))["items"][0]
    assert hit["title"] == "Printer broken" and "internal_note" not in hit


async def test_soft_deleted_and_bad_input(http, people, world) -> None:  # noqa: ANN001
    deleted = await http.delete(f"/tickets/{world['mine']}", headers=people["c1"])
    assert deleted.status_code == 204
    assert (await search(http, people["admin"], "printer"))["total"] == 1
    for params in ({"q": ""}, {"q": "   "}, {"q": "printer", "limit": 101}, {"q": "printer", "limit": 0}, {"q": "x" * 201}):
        response = await http.get("/tickets/search", params=params, headers=people["admin"])
        assert response.status_code == 422, (params, response.text)
    hostile = await search(http, people["admin"], "'; drop table tickets; --")
    assert hostile["items"] == [] and hostile["total"] == 0
    assert (await search(http, people["admin"], "printer", limit=1))["items"].__len__() == 1
    assert (await http.get("/tickets/search?q=printer")).status_code in (401, 403)
    assert (await http.get(f"/tickets/{world['other']}", headers=people["c2"])).status_code == 200  # /search is not an id


async def test_fts_and_the_fake_opensearch_return_the_same_filtered_set(
    http, people, monkeypatch, world  # noqa: ANN001
) -> None:
    queries = [("c1", "printer"), ("c2", "printer"), ("admin", "printer"), ("c1", "vipescalation"), ("admin", "vipescalation")]
    fts = {(w, q): await search(http, people[w], q) for w, q in queries}
    monkeypatch.setenv("SEARCH_BACKEND", "opensearch-fake")
    fake_engine().docs.clear()
    # indexing happens on write: touch both rows so the engine holds them
    for who, key in (("c1", "mine"), ("c2", "other")):
        patched = await http.patch(f"/tickets/{world[key]}", json={"title": "Printer broken" if key == "mine" else "Printer jammed"}, headers=people[who])
        assert patched.status_code == 200, patched.text
    assert set(fake_engine().docs["Ticket"]) == {world["mine"], world["other"]}
    for who, q in queries:
        got = await search(http, people[who], q)
        assert sorted(i["id"] for i in got["items"]) == sorted(i["id"] for i in fts[(who, q)]["items"]), (who, q)
        assert got["total"] == fts[(who, q)]["total"], (who, q)
        assert all("internal_note" not in i for i in got["items"] if who != "admin")


async def test_a_stale_or_hostile_index_cannot_widen_access(http, people, monkeypatch, world) -> None:  # noqa: ANN001
    monkeypatch.setenv("SEARCH_BACKEND", "opensearch-fake")
    engine = fake_engine()
    engine.docs.clear()
    # the index claims both rows (and a row that does not exist) match for c1, and holds the note too
    await engine.index("Ticket", world["other"], {"title": "Printer jammed", "internal_note": "vipescalation"})
    await engine.index("Ticket", world["mine"], {"title": "Printer broken", "internal_note": "vipescalation"})
    await engine.index("Ticket", "00000000-0000-4000-8000-0000000000ff", {"title": "Printer ghost"})
    await engine.index("Ticket", "not-a-uuid", {"title": "Printer junk"})
    c1 = await search(http, people["c1"], "printer")
    assert [i["id"] for i in c1["items"]] == [world["mine"]] and c1["total"] == 1
    assert (await search(http, people["c1"], "vipescalation"))["total"] == 0  # hidden field never queried
    await http.delete(f"/tickets/{world['mine']}", headers=people["c1"])
    assert world["mine"] not in engine.docs["Ticket"]  # delete reaches the index
    assert (await search(http, people["c1"], "printer"))["total"] == 0


async def test_fts_does_not_touch_the_index(http, people, monkeypatch, world) -> None:  # noqa: ANN001
    fake_engine().docs.clear()
    assert search_config.backend() == "fts"
    patched = await http.patch(f"/tickets/{world['mine']}", json={"title": "Printer fixed"}, headers=people["c1"])
    assert patched.status_code == 200
    assert fake_engine().docs == {}


async def test_startup_refuses_a_misconfigured_backend(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("SEARCH_BACKEND", "opensearch")
    monkeypatch.delenv("SEARCH_OPENSEARCH_URL", raising=False)
    import app.main as main  # noqa: PLC0415

    async def no_lock() -> None:
        return None

    monkeypatch.setattr(main, "get_auth_settings", lambda: None)
    monkeypatch.setattr(main, "ensure_provider_lock", no_lock)
    with pytest.raises(search_config.SearchConfigError, match="SEARCH_OPENSEARCH_URL"):
        async with app.router.lifespan_context(app):
            pass
    monkeypatch.setenv("SEARCH_BACKEND", "solr")
    with pytest.raises(search_config.SearchConfigError):
        search_config.check_boot()
    monkeypatch.setenv("SEARCH_BACKEND", "opensearch-fake")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(search_config.SearchConfigError, match="production"):
        search_config.check_boot()
    monkeypatch.setenv("SEARCH_BACKEND", "opensearch")
    monkeypatch.setenv("SEARCH_OPENSEARCH_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("APP_ENV", "development")
    search_config.check_boot()  # configured: boots (the engine is only called by a search)


async def test_reindex_streams_every_live_row_into_the_engine(http, people, monkeypatch, capsys, world) -> None:  # noqa: ANN001
    gone = await make(http, people["c2"], "Printer deleted")
    assert (await http.delete(f"/tickets/{gone}", headers=people["c2"])).status_code == 204
    # fts: the rows were never indexed, and the command says there is nothing to rebuild
    assert reindex_cli.main([]) == 0 and "no index to rebuild" in capsys.readouterr().out
    with pytest.raises(search_config.SearchConfigError, match="no index"):
        await reindex_cli.reindex()
    monkeypatch.setenv("SEARCH_BACKEND", "opensearch-fake")
    fake_engine().docs.clear()
    assert (await search(http, people["c1"], "printer"))["total"] == 0  # engine empty: recall gap, not a leak
    done = await reindex_cli.reindex(batch=1)  # one row per batch: the paging is exercised
    assert done == {"Ticket": 2}
    assert set(fake_engine().docs["Ticket"]) == {world["mine"], world["other"]}  # the deleted row is not in
    assert (await search(http, people["c1"], "printer"))["total"] == 1
    assert (await search(http, people["admin"], "printer"))["total"] == 2
    # the hidden field is in the document (same builder as the hook) but still unsearchable for c1
    assert (await search(http, people["c1"], "vipescalation"))["total"] == 0
    assert (await search(http, people["admin"], "vipescalation"))["total"] == 1
    assert await reindex_cli.reindex("Ticket") == {"Ticket": 2}  # idempotent
    with pytest.raises(search_config.SearchConfigError, match="not searchable"):
        await reindex_cli.reindex("Nope")
