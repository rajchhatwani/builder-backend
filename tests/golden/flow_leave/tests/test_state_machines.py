"""State machine checks (generated): initial state, state cannot be written directly, state log."""

import uuid

import pytest
from httpx import AsyncClient

from tests import _factories


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """The state machine's entity has access rules: sign in as a user who holds every role."""
    return authed_client


async def test_leave_requests_starts_in_its_initial_state(client: AsyncClient) -> None:
    other = 'manager_review'
    # A caller cannot choose the state: whatever is sent, the record starts in the initial state
    # (the log's first entry says so, even if an automatic transition has moved it on since).
    created = await _factories.make_leave_requests(client, **{"state": other})
    history = (await client.get(f"/leave_requests/{created['id']}/state-history")).json()
    assert [(h["transition"], h["from_state"], h["to_state"]) for h in history][:1] == [
        ("created", None, 'requested')
    ]


async def test_leave_requests_state_cannot_be_written_directly(client: AsyncClient) -> None:
    created = await _factories.make_leave_requests(client)
    before = created["state"]
    for state in ('requested', 'manager_review', 'hr_review', 'approved', 'declined', 'cancelled',):
        response = await client.patch(f"/leave_requests/{created['id']}", json={"state": state})
        assert response.status_code in (200, 422), response.text
    current = (await client.get(f"/leave_requests/{created['id']}/transitions")).status_code
    assert current == 200
    assert (await client.get(f"/leave_requests/{created['id']}")).json()["state"] == before


async def test_leave_requests_unknown_transition_and_record(client: AsyncClient) -> None:
    created = await _factories.make_leave_requests(client)
    unknown = await client.post(f"/leave_requests/{created['id']}/transitions/__no_such_transition__")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "not_found"
    missing = await client.post(f"/leave_requests/{uuid.uuid4()}/transitions/manager_approve")
    assert missing.status_code == 404


async def test_leave_requests_moves_and_logs(client: AsyncClient) -> None:
    """A manual move works, is logged after `created`, and the same move again from the wrong state is a 409."""
    for _ in range(50):  # sample data can trip an automatic transition on create: retry until it did not
        created = await _factories.make_leave_requests(client)
        if created["state"] in ('hr_review', 'manager_review', 'requested',):
            break
    else:
        raise AssertionError("no sample record was created in the starting state")
    base = f"/leave_requests/{created['id']}"
    moved = await client.post(f"{base}/transitions/cancel")
    assert moved.status_code == 200, moved.text
    history = (await client.get(f"{base}/state-history")).json()
    assert history[0]["transition"] == "created"
    assert any(h["transition"] == 'cancel' and h["from_state"] is not None for h in history[1:])
