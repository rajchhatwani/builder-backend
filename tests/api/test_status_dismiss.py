"""CO-6: dismiss / undo the optional `consider_auth` next step, stored per project."""

from httpx import AsyncClient

from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org


async def ready_project(client: AsyncClient) -> str:
    pid = await make_project(client)
    await make_entity(client, pid, "Item")
    return pid


async def test_dismiss_skips_consider_auth_and_undo_restores_it(client: AsyncClient) -> None:
    pid = await ready_project(client)
    base = f"/projects/{pid}/status"
    assert (await client.get(base)).json()["next_step"]["id"] == "consider_auth"
    done = await client.post(f"{base}/dismiss", json={"step": "consider_auth"})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["next_step"]["id"] == "generate" and body["ready"] is True
    assert [(s["id"], s["dismissed"]) for s in body["dismissed_steps"]] == [("consider_auth", True)]
    assert body["next_step"]["dismissed"] is False
    # persisted and idempotent
    assert (await client.post(f"{base}/dismiss", json={"step": "consider_auth"})).status_code == 200
    assert (await client.get(base)).json()["next_step"]["id"] == "generate"
    undone = await client.delete(f"{base}/dismiss/consider_auth")
    assert undone.status_code == 200
    assert undone.json()["next_step"]["id"] == "consider_auth"
    assert undone.json()["dismissed_steps"] == []
    assert (await client.delete(f"{base}/dismiss/consider_auth")).status_code == 200


async def test_unknown_or_undismissable_step_is_422(client: AsyncClient) -> None:
    pid = await ready_project(client)
    base = f"/projects/{pid}/status"
    for step in ("nope", "generate", "fix_issues", ""):
        assert (await client.post(f"{base}/dismiss", json={"step": step})).status_code == 422
    assert (await client.delete(f"{base}/dismiss/nope")).status_code == 422
    assert (await client.post(f"{base}/dismiss", json={})).status_code == 422
    assert (await client.get(base)).json()["dismissed_steps"] == []


async def test_dismiss_does_not_disturb_behaviour_section_versions(client: AsyncClient) -> None:
    pid = await ready_project(client)
    await client.put(f"/projects/{pid}/behavior/settings", json={"settings": []})
    await client.post(f"/projects/{pid}/status/dismiss", json={"step": "consider_auth"})
    got = (await client.get(f"/projects/{pid}/behavior/settings")).json()
    assert got["version"] == 1
    again = await client.put(
        f"/projects/{pid}/behavior/settings", json={"settings": [], "expected_version": 1}
    )
    assert again.status_code == 200
    assert (await client.get(f"/projects/{pid}/status")).json()["next_step"]["id"] == "generate"


async def test_viewer_cannot_dismiss_and_strangers_are_denied(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    stranger = await client_for("stranger@example.com")
    viewer = await client_for("viewer@example.com")
    pid = await ready_project(owner)
    await add_to_project_org(pid, "viewer@example.com")
    added = await owner.post(
        f"/projects/{pid}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    base = f"/projects/{pid}/status"
    body = {"step": "consider_auth"}
    assert (await viewer.post(f"{base}/dismiss", json=body)).status_code == 403
    assert (await stranger.post(f"{base}/dismiss", json=body)).status_code == 404
    assert (await stranger.delete(f"{base}/dismiss/consider_auth")).status_code == 404
    assert (await owner.post(f"{base}/dismiss", json=body)).status_code == 200
    assert (await viewer.delete(f"{base}/dismiss/consider_auth")).status_code == 403
    assert (await stranger.get(base)).status_code == 404
    # a second project of the stranger is unaffected
    other = await ready_project(stranger)
    assert (await stranger.get(f"/projects/{other}/status")).json()["dismissed_steps"] == []
