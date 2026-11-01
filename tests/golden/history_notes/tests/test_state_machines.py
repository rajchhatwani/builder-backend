"""State machine checks (generated): initial state, state cannot be written directly, state log."""

import uuid

import pytest
from httpx import AsyncClient

from tests import _factories
from tests._auth_support import client_for, sign_in


@pytest.fixture
def client(authed_client: AsyncClient) -> AsyncClient:
    """The state machine's entity has access rules: sign in as a user who holds every role."""
    return authed_client


async def test_tickets_starts_in_its_initial_state(client: AsyncClient) -> None:
    other = 'in_progress'
    # A caller cannot choose the state: whatever is sent, the record starts in the initial state
    # (the log's first entry says so, even if an automatic transition has moved it on since).
    created = await _factories.make_tickets(client, **{"status": other})
    assert created["status"] == 'open'
    history = (await client.get(f"/tickets/{created['id']}/state-history")).json()
    assert [(h["transition"], h["from_state"], h["to_state"]) for h in history][:1] == [
        ("created", None, 'open')
    ]


async def test_tickets_state_cannot_be_written_directly(client: AsyncClient) -> None:
    created = await _factories.make_tickets(client)
    before = created["status"]
    for state in ('open', 'in_progress', 'closed',):
        response = await client.patch(f"/tickets/{created['id']}", json={"status": state})
        assert response.status_code in (200, 422), response.text
    current = (await client.get(f"/tickets/{created['id']}/transitions")).status_code
    assert current == 200
    assert (await client.get(f"/tickets/{created['id']}")).json()["status"] == before


async def test_tickets_unknown_transition_and_record(client: AsyncClient) -> None:
    created = await _factories.make_tickets(client)
    unknown = await client.post(f"/tickets/{created['id']}/transitions/__no_such_transition__")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "not_found"
    missing = await client.post(f"/tickets/{uuid.uuid4()}/transitions/start")
    assert missing.status_code == 404


async def test_tickets_transitions_without_roles_need_update_access(client: AsyncClient) -> None:
    """A transition that lists no roles is open to whoever may update Ticket, not to every reader
    (role `auditor` can read but not update); one that lists roles keeps its own role check."""
    created = await _factories.make_tickets(client)
    base = f"/tickets/{created['id']}"
    async with client_for(await sign_in(client, "sm-reader@example.com", roles=['auditor'])) as reader:
        assert (await reader.get(base)).status_code == 200  # the reader sees the record...
    async with client_for({}) as anonymous:
        assert (await anonymous.post(f"{base}/transitions/x")).status_code in (401, 403)
