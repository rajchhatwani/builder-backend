"""B2-9: migration plan endpoint, plan shown in preview, destructive generate refused (409)."""

from httpx import AsyncClient

from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_spec import build_blog

MISSING = "00000000-0000-0000-0000-000000000000"


async def _drop_a_field(client: AsyncClient, project_id: str) -> str:
    entities = (await client.get(f"/projects/{project_id}/entities")).json()
    items = entities["items"] if isinstance(entities, dict) else entities
    for e in items:
        fields = (await client.get(f"/entities/{e['id']}/fields")).json()
        rows = fields["items"] if isinstance(fields, dict) else fields
        if rows:
            res = await client.delete(f"/fields/{rows[0]['id']}")
            assert res.status_code == 204, res.text
            return str(rows[0]["name"])
    raise AssertionError("blog has no fields")


async def test_first_generation_plans_against_empty_spec_and_is_not_destructive(
    client: AsyncClient,
) -> None:
    pid = await build_blog(client)
    res = await client.post(f"/projects/{pid}/migration-plan", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["first_generation"] is True
    assert body["old_spec_hash"] is None and body["new_spec_hash"]
    assert body["plan"]["requires_confirmation"] is False
    assert body["allow_destructive_required"] is False
    assert {s["kind"] for s in body["plan"]["steps"]} == {"create_table"}
    assert "Migration plan" in body["text"]
    # no body at all is also fine
    assert (await client.post(f"/projects/{pid}/migration-plan")).status_code == 200


async def test_preview_shows_the_plan(client: AsyncClient) -> None:
    pid = await build_blog(client)
    body = (await client.post(f"/projects/{pid}/generate/preview")).json()
    assert body["migration"]["first_generation"] is True
    assert body["migration"]["plan"]["steps"]


async def test_unchanged_spec_after_generation_gives_empty_plan(client: AsyncClient) -> None:
    pid = await build_blog(client)
    gen = await client.get(f"/projects/{pid}/generate/download")
    assert gen.status_code == 200
    body = (await client.post(f"/projects/{pid}/migration-plan", json={})).json()
    assert body["first_generation"] is False
    assert body["plan"]["steps"] == []
    assert body["against_generation_id"] == gen.headers["x-generation-id"]
    assert (await client.get(f"/projects/{pid}/generate/download")).status_code == 200


async def test_destructive_change_is_refused_without_flag_and_allowed_with_it(
    client: AsyncClient,
) -> None:
    pid = await build_blog(client)
    assert (await client.get(f"/projects/{pid}/generate/download")).status_code == 200
    dropped = await _drop_a_field(client, pid)

    plan = (await client.post(f"/projects/{pid}/migration-plan", json={})).json()
    assert plan["allow_destructive_required"] is True
    assert any(
        s["kind"] == "drop_column" and s["field"] == dropped and s["safety"] == "destructive"
        for s in plan["plan"]["steps"]
    )
    preview = (await client.post(f"/projects/{pid}/generate/preview")).json()
    assert preview["migration"]["plan"]["requires_confirmation"] is True

    before = (await client.get(f"/projects/{pid}/generations")).json()["total"]
    refused = await client.get(f"/projects/{pid}/generate/download")
    assert refused.status_code == 409, refused.text
    err = refused.json()
    assert err["code"] == "destructive_migration"
    assert err["details"][0]["plan"]["requires_confirmation"] is True
    assert (await client.get(f"/projects/{pid}/generations")).json()["total"] == before

    ok = await client.get(f"/projects/{pid}/generate/download", params={"allow_destructive": True})
    assert ok.status_code == 200, ok.text
    assert (await client.get(f"/projects/{pid}/generations")).json()["total"] == before + 1
    # the dropped column is now part of the last generation: nothing destructive remains
    assert (await client.get(f"/projects/{pid}/generate/download")).status_code == 200


async def test_against_generation_id_and_bad_inputs(client: AsyncClient) -> None:
    pid = await build_blog(client)
    first = (await client.get(f"/projects/{pid}/generate/download")).headers["x-generation-id"]
    await _drop_a_field(client, pid)
    body = (
        await client.post(f"/projects/{pid}/migration-plan", json={"against_generation_id": first})
    ).json()
    assert body["against_generation_id"] == first and body["plan"]["requires_confirmation"]
    assert (
        await client.post(
            f"/projects/{pid}/migration-plan", json={"against_generation_id": MISSING}
        )
    ).status_code == 404
    bad = await client.post(
        f"/projects/{pid}/migration-plan",
        json={"renames": [{"entity": "Nope", "from": "a", "to": "b"}]},
    )
    assert bad.status_code == 422 and "migration_plan_invalid" in bad.text
    assert (
        await client.post(f"/projects/{pid}/migration-plan", json={"renames": [{"x": 1}]})
    ).status_code == 422


async def test_generation_of_another_project_is_a_404(client: AsyncClient) -> None:
    a = await build_blog(client)
    b = await make_project(client, "Other")
    gen = (await client.get(f"/projects/{a}/generate/download")).headers["x-generation-id"]
    res = await client.post(f"/projects/{b}/migration-plan", json={"against_generation_id": gen})
    assert res.status_code == 404


async def test_other_customer_gets_404_and_viewer_is_denied(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    stranger = await client_for("stranger@example.com")
    viewer = await client_for("viewer@example.com")
    editor = await client_for("editor@example.com")
    pid = await make_project(owner)
    await make_entity(owner, pid, "Item")
    for email, role in (("viewer@example.com", "viewer"), ("editor@example.com", "editor")):
        await add_to_project_org(pid, email)
        r = await owner.post(f"/projects/{pid}/members", json={"email": email, "role": role})
        assert r.status_code == 201, r.text
    gen = (await owner.get(f"/projects/{pid}/generate/download")).headers["x-generation-id"]

    assert (await stranger.post(f"/projects/{pid}/migration-plan", json={})).status_code == 404
    assert (
        await stranger.get(f"/projects/{pid}/generate/download", params={"allow_destructive": True})
    ).status_code == 404
    assert (await viewer.post(f"/projects/{pid}/migration-plan", json={})).status_code == 403
    assert (await editor.post(f"/projects/{pid}/migration-plan", json={})).status_code == 200
    # a viewer may download as before but cannot pass the destructive override
    assert (await viewer.get(f"/projects/{pid}/generate/download")).status_code == 200
    denied = await viewer.get(
        f"/projects/{pid}/generate/download", params={"allow_destructive": True}
    )
    assert denied.status_code == 403
    assert gen


async def _break_snapshot(project_id: str, value: str | None) -> str:
    """Replace the newest generation's snapshot with raw JSON (`value`) and return its id."""
    import uuid as _uuid

    from sqlalchemy import text

    from tests.api.conftest import _FACTORY

    async with _FACTORY[0]() as db:
        row = (
            await db.execute(
                text("SELECT id FROM generations WHERE project_id = :p ORDER BY created_at DESC"),
                {"p": _uuid.UUID(project_id)},
            )
        ).first()
        assert row is not None
        await db.execute(
            text("UPDATE generations SET spec_snapshot = CAST(:v AS jsonb) WHERE id = :i"),
            {"v": value if value is not None else "null", "i": row[0]},
        )
        await db.commit()
        return str(row[0])


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "raw",
    ['"corrupt"', '{"project": 5}', '{"unrelated": true}', None, "[1, 2]"],
    ids=["string", "wrong-schema", "foreign-schema", "json-null", "list"],
)
async def test_unreadable_baseline_fails_closed_unless_explicitly_accepted(
    client: AsyncClient, raw: str | None
) -> None:
    pid = await build_blog(client)
    assert (await client.get(f"/projects/{pid}/generate/download")).status_code == 200
    gen_id = await _break_snapshot(pid, raw)
    total = (await client.get(f"/projects/{pid}/generations")).json()["total"]

    plan = await client.post(f"/projects/{pid}/migration-plan", json={})
    assert plan.status_code == 409, plan.text
    err = plan.json()
    assert err["code"] == "migration_baseline_unreadable"
    assert err["details"] == [{"generation_id": gen_id}]
    assert "project" not in str(err["details"]) and "entities" not in plan.text

    dl = await client.get(f"/projects/{pid}/generate/download")
    assert dl.status_code == 409 and dl.json()["code"] == "migration_baseline_unreadable"
    assert (await client.get(f"/projects/{pid}/generations")).json()["total"] == total

    # allow_destructive alone does not bypass it
    both = await client.get(f"/projects/{pid}/generate/download", params={"allow_destructive": True})
    assert both.status_code == 409

    ok = await client.post(
        f"/projects/{pid}/migration-plan", params={"accept_unreadable_baseline": True}, json={}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["old_snapshot_unusable"] is True and ok.json()["first_generation"] is False
    ok_dl = await client.get(
        f"/projects/{pid}/generate/download", params={"accept_unreadable_baseline": True}
    )
    assert ok_dl.status_code == 200, ok_dl.text
    # the new generation is a readable baseline again
    assert (await client.get(f"/projects/{pid}/generate/download")).status_code == 200


async def test_preview_reports_an_unreadable_baseline_without_failing(
    client: AsyncClient,
) -> None:
    pid = await build_blog(client)
    assert (await client.get(f"/projects/{pid}/generate/download")).status_code == 200
    await _break_snapshot(pid, '"corrupt"')
    body = (await client.post(f"/projects/{pid}/generate/preview")).json()
    assert body["migration"]["old_snapshot_unusable"] is True
    assert body["migration"]["first_generation"] is False


async def test_missing_snapshot_history_is_still_a_first_generation(client: AsyncClient) -> None:
    pid = await build_blog(client)
    body = (await client.post(f"/projects/{pid}/migration-plan", json={})).json()
    assert body["first_generation"] is True and body["old_snapshot_unusable"] is False


async def test_accepting_an_unreadable_baseline_needs_editor_and_mcp_never_does(
    client_for: ClientFor,
) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    pid = await make_project(owner)
    await make_entity(owner, pid, "Item")
    await add_to_project_org(pid, "viewer@example.com")
    r = await owner.post(f"/projects/{pid}/members", json={"email": "viewer@example.com", "role": "viewer"})
    assert r.status_code == 201, r.text
    assert (await owner.get(f"/projects/{pid}/generate/download")).status_code == 200
    await _break_snapshot(pid, '"corrupt"')
    flag = {"accept_unreadable_baseline": True}
    assert (await viewer.post(f"/projects/{pid}/migration-plan", params=flag, json={})).status_code == 403
    assert (await viewer.get(f"/projects/{pid}/generate/download", params=flag)).status_code == 403
    # the MCP generate path never passes the flag: it fails closed
    from app.services.generation_service import GenerationService

    import inspect

    sig = inspect.signature(GenerationService.download)
    assert sig.parameters["accept_unreadable_baseline"].default is False
    assert (await owner.get(f"/projects/{pid}/generate/download")).status_code == 409
