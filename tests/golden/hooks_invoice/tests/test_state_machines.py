"""State machine checks (generated): initial state, state cannot be written directly, state log."""

import uuid

import pytest
from httpx import AsyncClient

from tests import _factories


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """The state machine's entity has access rules: sign in as a user who holds every role."""
    return authed_client


async def test_invoices_starts_in_its_initial_state(client: AsyncClient) -> None:
    other = 'submitted'
    # A caller cannot choose the state: whatever is sent, the record starts in the initial state
    # (the log's first entry says so, even if an automatic transition has moved it on since).
    created = await _factories.make_invoices(client, **{"status": other})
    history = (await client.get(f"/invoices/{created['id']}/state-history")).json()
    assert [(h["transition"], h["from_state"], h["to_state"]) for h in history][:1] == [
        ("created", None, 'draft')
    ]


async def test_invoices_state_cannot_be_written_directly(client: AsyncClient) -> None:
    created = await _factories.make_invoices(client)
    before = created["status"]
    for state in ('draft', 'submitted', 'pending_approval', 'approved', 'paid', 'rejected',):
        response = await client.patch(f"/invoices/{created['id']}", json={"status": state})
        assert response.status_code in (200, 422), response.text
    current = (await client.get(f"/invoices/{created['id']}/transitions")).status_code
    assert current == 200
    assert (await client.get(f"/invoices/{created['id']}")).json()["status"] == before


async def test_invoices_unknown_transition_and_record(client: AsyncClient) -> None:
    created = await _factories.make_invoices(client)
    unknown = await client.post(f"/invoices/{created['id']}/transitions/__no_such_transition__")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "not_found"
    missing = await client.post(f"/invoices/{uuid.uuid4()}/transitions/submit")
    assert missing.status_code == 404
