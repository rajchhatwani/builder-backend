"""Audit B1-021 API regressions (F-0214 preview off-loop + cap)."""

import threading
from typing import Any

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_project


async def test_preview_runs_in_a_worker_thread(client: AsyncClient, monkeypatch: Any) -> None:
    from app.core import doc_engine

    seen: list[int] = []
    real = doc_engine.render_pdf

    def spy(*a: Any, **k: Any) -> bytes:
        seen.append(threading.get_ident())
        return real(*a, **k)

    monkeypatch.setattr(doc_engine, "render_pdf", spy)
    project_id = await make_project(client)
    body = {"template": {"blocks": [{"type": "paragraph", "text": "hi"}]}, "data": {}}
    r = await client.post(f"/projects/{project_id}/documents/preview", json=body)
    assert r.status_code == 200, r.text
    assert seen and seen[0] != threading.get_ident()


async def test_preview_refuses_a_huge_table_grid_fast(client: AsyncClient) -> None:
    project_id = await make_project(client)
    cols = [{"header": "H", "value": "{{x}}"}] * 12
    template = {"blocks": [{"type": "table", "source": "items", "columns": cols}] * 200}
    data = {"items": [{"x": "y" * 40}] * 500}
    r = await client.post(
        f"/projects/{project_id}/documents/preview", json={"template": template, "data": data}
    )
    assert r.status_code == 422, r.text


async def test_keycloak_source_project_of_another_org_is_404(
    client: AsyncClient, client_for: Any
) -> None:
    from tests.api.test_keycloak import settings

    victim = await make_project(client, "Victim")
    assert (
        await client.put(f"/projects/{victim}/keycloak", json=settings(mode="own"))
    ).status_code == 200
    other = await client_for("attacker@example.com")
    mine = await make_project(other, "Mine")
    r = await other.put(
        f"/projects/{mine}/keycloak", json=settings(mode="shared", source_project_id=victim)
    )
    assert r.status_code == 404, r.text


_PUTS = [
    ("documents", {}),
    ("observability", {}),
    ("deployment", {"cloud": "aws", "region": "eu-west-1", "github_repo": "acme/notes"}),
    ("authorization", {}),
]


@pytest.mark.parametrize(("path", "body"), _PUTS)
async def test_expected_version_saves_lock_the_row_and_a_first_save_race_is_409(
    client: AsyncClient, engine: Any, path: str, body: dict[str, Any]
) -> None:
    from sqlalchemy import event

    project_id = await make_project(client)
    url = f"/projects/{project_id}/{path}"
    assert (await client.put(url, json=body)).status_code == 200
    seen: list[str] = []

    def spy(conn: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", spy)
    try:
        r = await client.put(url, json={**body, "expected_version": 1})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", spy)
    assert r.status_code == 200, r.text
    assert any("FOR UPDATE" in s and "project_" in s for s in seen), seen[:5]


async def test_first_save_race_answers_409_not_500(client: AsyncClient, monkeypatch: Any) -> None:
    from app.services.documents_service import DocumentsService

    project_id = await make_project(client)
    url = f"/projects/{project_id}/documents"
    assert (await client.put(url, json={})).status_code == 200

    async def no_row(self: Any, project_id: Any, *, lock: bool = False) -> None:
        return None  # as if both savers saw "never saved"

    monkeypatch.setattr(DocumentsService, "_row", no_row)
    r = await client.put(url, json={})
    assert r.status_code == 409, r.text


async def _perm_setup(client: AsyncClient) -> tuple[str, str]:
    from tests.api._auth_helpers import make_auth, make_entity, make_role

    project_id = await make_project(client)
    await make_auth(client, project_id)
    entity_id = await make_entity(client, project_id)
    await make_role(client, project_id, "admin")
    first = await client.post(
        f"/projects/{project_id}/permissions",
        json={"permissions": [{"entity_id": entity_id, "operation": "list", "roles": ["admin"]}]},
    )
    assert first.status_code == 200, first.text
    return project_id, entity_id


async def test_permissions_post_that_makes_an_entity_public_needs_confirmation(
    client: AsyncClient,
) -> None:
    project_id, entity_id = await _perm_setup(client)
    url = f"/projects/{project_id}/permissions"
    entry = {"entity_id": entity_id, "operation": "list", "roles": []}
    refused = await client.post(url, json={"permissions": [entry]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "access_weakened"
    saved = (await client.get(url)).json()
    assert [p["roles"] for p in saved["items"]] == [["admin"]]  # nothing changed
    ok = await client.post(url, json={"permissions": [entry], "confirm_weakening": True})
    assert ok.status_code == 200, ok.text
    assert ok.json()[0]["roles"] == []


async def test_permissions_patch_that_makes_an_entity_public_needs_confirmation(
    client: AsyncClient,
) -> None:
    project_id, _ = await _perm_setup(client)
    perm = (await client.get(f"/projects/{project_id}/permissions")).json()["items"][0]
    url = f"/permissions/{perm['id']}"
    refused = await client.patch(url, json={"roles": []})
    assert refused.status_code == 409, refused.text
    assert (await client.get(url)).json()["roles"] == ["admin"]
    ok = await client.patch(url, json={"roles": [], "confirm_weakening": True})
    assert ok.status_code == 200, ok.text
    assert ok.json()["roles"] == []


async def test_put_spec_that_widens_access_needs_confirmation(client: AsyncClient) -> None:
    project_id, _ = await _perm_setup(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    widened = False
    for perm in spec["auth"]["permissions"]:
        perm["roles"] = []
        widened = True
    assert widened, spec["auth"]
    refused = await client.put(f"/projects/{project_id}/spec", json=spec)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "access_weakened"
    ok = await client.put(f"/projects/{project_id}/spec?confirm_weakening=true", json=spec)
    assert ok.status_code == 200, ok.text
