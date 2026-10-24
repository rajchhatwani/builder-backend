"""Scenario tests for the generated `docs_desk` project: a document bound to a stored record. Copied into
the project's tests/ folder by tests/e2e/test_documents_stack.py and run against a real Postgres.

Template `ticket_summary` is bound to Ticket and may be rendered by customer and staff. Ticket.get itself
allows only admin and customer, and a customer only reads their own tickets (row rule "owner"), so the
PDF follows the entity's rules, not just the template's roles.
"""

import io

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.main import app


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


async def make_ticket(http: AsyncClient, headers: dict, subject: str) -> str:
    response = await http.post("/tickets", json={"subject": subject}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_a_customer_renders_their_own_ticket_with_its_own_values(http: AsyncClient) -> None:
    customer = await sign_in(http, "cust@example.com", roles=["customer"])
    ticket = await make_ticket(http, customer, "Printer on fire")

    response = await http.post(
        f"/documents/ticket_summary/records/{ticket}",
        json={"extra": {"agent": "Alex", "subject": "SPOOFED"}},
        headers=customer,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    text = text_of(response.content)
    assert "Printer on fire" in text
    assert "Alex" in text  # extra data is available...
    assert "SPOOFED" not in text  # ...but can never replace the record's own values


async def test_the_entity_access_rules_decide_who_gets_a_pdf(http: AsyncClient) -> None:
    customer = await sign_in(http, "cust@example.com", roles=["customer"])
    staff = await sign_in(http, "staff@example.com", roles=["staff"], n=1)
    other = await sign_in(http, "other@example.com", roles=["customer"], n=2)
    admin = await sign_in(http, "boss@example.com", roles=["admin"], n=3)
    ticket = await make_ticket(http, customer, "Mine")
    url = f"/documents/ticket_summary/records/{ticket}"

    # another customer holds the template's role, but the ticket is not theirs: not found
    assert (await http.post(url, json={}, headers=other)).status_code == 404
    # staff hold the template's role but may not read tickets at all: the entity's rule applies
    assert (await http.post(url, json={}, headers=staff)).status_code == 403
    # an admin holds the roles it inherits, so the template lets it in, but the "owner" row rule of
    # Ticket.get still applies: someone else's ticket is not found
    assert (await http.post(url, json={}, headers=admin)).status_code == 404
    assert (await http.post(url, json={})).status_code == 401


async def test_a_missing_record_is_a_404_not_a_pdf(http: AsyncClient) -> None:
    customer = await sign_in(http, "cust@example.com", roles=["customer"])
    url = "/documents/ticket_summary/records/00000000-0000-0000-0000-0000000000aa"
    assert (await http.post(url, json={}, headers=customer)).status_code == 404
