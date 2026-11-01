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
    for state in ('draft', 'submitted', 'pending_approval', 'approved', 'paid', 'rejected', 'withdrawn',):
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


async def test_invoices_transitions_without_roles_need_update_access(client: AsyncClient) -> None:
    """A transition that lists no roles is open to whoever may update Invoice, not to every reader
    (role `approver` can read but not update); one that lists roles keeps its own role check."""
    created = await _factories.make_invoices(client)
    base = f"/invoices/{created['id']}"
    async with client_for(await sign_in(client, "sm-reader@example.com", roles=['approver'])) as reader:
        assert (await reader.get(base)).status_code == 200  # the reader sees the record...
        refused = await reader.post(f"{base}/transitions/withdraw")
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "forbidden"
    async with client_for(await sign_in(client, "sm-roled@example.com", roles=['clerk'])) as roled:
        moved = await roled.post(f"{base}/transitions/submit")
        assert moved.status_code == 200, moved.text  # listed role: unchanged, no update right needed
        created = await _factories.make_invoices(client)
        base = f"/invoices/{created['id']}"
    async with client_for({}) as anonymous:
        assert (await anonymous.post(f"{base}/transitions/withdraw")).status_code in (401, 403)
    allowed = await client.post(f"{base}/transitions/withdraw")  # holds every role, so may update
    assert allowed.status_code == 200, allowed.text
