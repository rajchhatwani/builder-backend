"""State machine checks (generated): initial state, state cannot be written directly, state log."""

import uuid

import pytest
from httpx import AsyncClient

from tests import _factories


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """The state machine's entity has access rules: sign in as a user who holds every role."""
    return authed_client


async def test_expenses_starts_in_its_initial_state(client: AsyncClient) -> None:
    other = 'approved'
    # A caller cannot choose the state: whatever is sent, the record starts in the initial state
    # (the log's first entry says so, even if an automatic transition has moved it on since).
    created = await _factories.make_expenses(client, **{"status": other})
    assert created["status"] == 'draft'
    history = (await client.get(f"/expenses/{created['id']}/state-history")).json()
    assert [(h["transition"], h["from_state"], h["to_state"]) for h in history][:1] == [
        ("created", None, 'draft')
    ]


async def test_expenses_state_cannot_be_written_directly(client: AsyncClient) -> None:
    created = await _factories.make_expenses(client)
    before = created["status"]
    for state in ('draft', 'approved',):
        response = await client.patch(f"/expenses/{created['id']}", json={"status": state})
        assert response.status_code in (200, 422), response.text
    current = (await client.get(f"/expenses/{created['id']}/transitions")).status_code
    assert current == 200
    assert (await client.get(f"/expenses/{created['id']}")).json()["status"] == before


async def test_expenses_unknown_transition_and_record(client: AsyncClient) -> None:
    created = await _factories.make_expenses(client)
    unknown = await client.post(f"/expenses/{created['id']}/transitions/__no_such_transition__")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "not_found"
    missing = await client.post(f"/expenses/{uuid.uuid4()}/transitions/approve")
    assert missing.status_code == 404
