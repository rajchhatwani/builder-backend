"""PDF documents behave as documented (generated): who may render, escaping, determinism, recomputed
totals and limits."""
# ruff: noqa: F811

import io
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader

from app.auth.service import effective_roles
from app.documents.data import TEMPLATES
from app.main import app
from tests._auth_support import ALL_ROLES, authed_client, outbox, sign_in  # noqa: F401

UNBOUND = [t for t in TEMPLATES.values() if t["entity"] is None]
BOUND = [t for t in TEMPLATES.values() if t["entity"] is not None]
COMPUTED = [t for t in UNBOUND if t["compute"]]


@pytest.fixture
async def http_client(outbox) -> AsyncIterator[AsyncClient]:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def allowed_for(template: dict) -> list[str]:  # noqa: ANN001
    """Roles that may render it, counting roles a role inherits (an admin holds what staff hold)."""
    return [r for r in ALL_ROLES if effective_roles([r]) & set(template["roles"])]


def denied_for(template: dict) -> list[str]:  # noqa: ANN001
    return [r for r in ALL_ROLES if r not in allowed_for(template)]


async def test_signed_out_callers_get_nothing(http_client: AsyncClient) -> None:
    assert (await http_client.get("/documents")).status_code == 401
    for t in UNBOUND:
        assert (await http_client.post(f"/documents/{t['id']}/render", json={})).status_code == 401
    for t in BOUND:
        url = f"/documents/{t['id']}/records/00000000-0000-0000-0000-000000000001"
        assert (await http_client.post(url, json={})).status_code == 401


async def test_the_list_shows_only_what_the_caller_may_render(authed_client: AsyncClient) -> None:
    body = (await authed_client.get("/documents")).json()
    assert {t["id"] for t in body} == {t["id"] for t in TEMPLATES.values() if allowed_for(t)}


@pytest.mark.parametrize("template", UNBOUND, ids=lambda t: t["id"])
async def test_a_template_renders_a_pdf_and_is_deterministic(
    authed_client: AsyncClient, template: dict  # noqa: ANN001
) -> None:
    if not allowed_for(template):
        pytest.skip("no role may render this template")
    first = await authed_client.post(f"/documents/{template['id']}/render", json={"data": {}})
    second = await authed_client.post(f"/documents/{template['id']}/render", json={"data": {}})
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "application/pdf"
    assert first.headers["cache-control"] == "no-store"
    assert first.content.startswith(b"%PDF")
    assert first.content == second.content  # same input, same bytes


@pytest.mark.parametrize("template", UNBOUND, ids=lambda t: t["id"])
async def test_only_the_templates_roles_may_render(
    http_client: AsyncClient, template: dict  # noqa: ANN001
) -> None:
    denied = denied_for(template)
    if not denied:
        pytest.skip("every role may render this template")
    headers = await sign_in(http_client, "denied@example.com", roles=denied[:1])
    response = await http_client.post(
        f"/documents/{template['id']}/render", json={"data": {}}, headers=headers
    )
    assert response.status_code == 403


@pytest.mark.parametrize("template", UNBOUND, ids=lambda t: t["id"])
async def test_data_can_never_inject_markup(
    authed_client: AsyncClient, template: dict  # noqa: ANN001
) -> None:
    if not allowed_for(template):
        pytest.skip("no role may render this template")
    hostile = "<b>bold</b> & <img src='http://169.254.169.254/'/> {" "{ item }}"
    data = {key: hostile for key in ("number", "title", "name", "recipient", "subject", "event")}
    response = await authed_client.post(f"/documents/{template['id']}/render", json={"data": data})
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")
    text = text_of(response.content)
    assert "<b>" not in text.replace("<b>bold</b>", "")  # shown as text when used, never interpreted


@pytest.mark.parametrize("template", COMPUTED, ids=lambda t: t["id"])
async def test_totals_are_recomputed_not_trusted(
    authed_client: AsyncClient, template: dict  # noqa: ANN001
) -> None:
    if not allowed_for(template):
        pytest.skip("no role may render this template")
    data = {
        "currency": "EUR",
        "items": [{"description": "Widget", "quantity": 3, "unit_price": "9.99", "tax_rate": 20}],
        "totals": {"subtotal": "1.00", "tax_total": "0.00", "total": "1.00"},  # a lie
    }
    response = await authed_client.post(f"/documents/{template['id']}/render", json={"data": data})
    assert response.status_code == 200, response.text
    text = text_of(response.content)
    assert "35.96 EUR" in text  # 3 x 9.99 = 29.97 net, 20% tax = 5.99
    assert "1.00 EUR" not in text


@pytest.mark.parametrize("template", COMPUTED, ids=lambda t: t["id"])
async def test_unacceptable_data_is_a_clear_422(
    authed_client: AsyncClient, template: dict  # noqa: ANN001
) -> None:
    if not allowed_for(template):
        pytest.skip("no role may render this template")
    url = f"/documents/{template['id']}/render"
    bad_number = {"items": [{"quantity": "many", "unit_price": 1}]}
    too_many = {"items": [{"quantity": 1, "unit_price": 1}] * 501}
    for data in (bad_number, too_many, {"items": "not a list"}):
        response = await authed_client.post(url, json={"data": data})
        assert response.status_code == 422, data
        assert response.json()["code"] == "invalid_document"


async def test_ticket_summary_is_rendered_through_the_Ticket_access_rules(
    http_client: AsyncClient,
) -> None:
    template = TEMPLATES["ticket_summary"]
    url = "/documents/ticket_summary/records/00000000-0000-0000-0000-0000000000aa"
    denied = denied_for(template)
    if denied:
        headers = await sign_in(http_client, "nodoc@example.com", roles=denied[:1])
        assert (await http_client.post(url, json={}, headers=headers)).status_code == 403
    if allowed_for(template):
        headers = await sign_in(http_client, "doc@example.com", roles=allowed_for(template)[:1], n=1)
        # a record that does not exist (or is outside the caller's rows) is a 404, never a PDF
        assert (await http_client.post(url, json={}, headers=headers)).status_code == 404
