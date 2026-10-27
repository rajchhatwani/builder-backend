"""PDF document templates API: persistence, library, live preview, validation, spec round trip."""

import copy
import io
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pypdf import PdfReader

from app.core import doc_library as lib
from tests.api._auth_helpers import make_project
from tests.api.conftest import add_to_project_org, ClientFor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def desk_spec() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads((FIXTURES / "docs_desk.json").read_text(encoding="utf-8"))
    return raw


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


async def project_with_documents(client: AsyncClient) -> str:
    project_id = await make_project(client, "Desk")
    response = await client.put(f"/projects/{project_id}/spec", json=desk_spec())
    assert response.status_code == 200, response.text
    return project_id


def invoice_template(**changes: Any) -> dict[str, Any]:
    entry = lib.get("invoice")
    base = {
        "id": "invoice",
        "title": "Invoice",
        "kind": "invoice",
        "compute": "items",
        "roles": ["staff"],
        "template": entry["template"],
    }
    base.update(changes)
    return base


# -- library and preview ----------------------------------------------------------------------


async def test_the_library_lists_ten_templates_with_reasons_and_sample_data(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    items = (await client.get(f"/projects/{project_id}/documents/library")).json()
    assert len(items) == 10
    assert {i["id"] for i in items} >= {"invoice", "receipt", "quote", "certificate", "ticket"}
    invoice = next(i for i in items if i["id"] == "invoice")
    assert invoice["why"] and invoice["industries"] and invoice["sample"]["items"]
    assert invoice["compute"] == "items"


async def test_preview_renders_the_pdf_the_generated_api_would_produce(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    entry = lib.get("invoice")
    response = await client.post(
        f"/projects/{project_id}/documents/preview",
        json={"template": entry["template"], "data": entry["sample"], "compute": "items"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert "1,967.39 EUR" in text_of(response.content)
    # same bytes the engine gives directly: the preview IS the generated behaviour
    from app.core import doc_engine

    assert response.content == doc_engine.render_pdf(
        entry["template"], entry["sample"], compute="items"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"template": {}},
        {"template": {"blocks": [{"type": "script"}]}},
        {"template": {"blocks": [{"type": "paragraph", "text": "{{a | nope}}"}]}},
        {
            "template": {"blocks": [{"type": "paragraph", "text": "x"}]},
            "data": {
                "a": {
                    "b": {
                        "c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": {"l": {"m": 1}}}}}}}}}}
                    }
                }
            },
        },
    ],
)
async def test_preview_refuses_bad_input_with_a_422(
    client: AsyncClient, body: dict[str, Any]
) -> None:
    project_id = await make_project(client)
    response = await client.post(f"/projects/{project_id}/documents/preview", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# -- persistence and validation ---------------------------------------------------------------


async def test_a_new_project_has_no_documents(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/documents")).json()
    assert body["version"] == 0 and body["templates"] == [] and body["enabled"] is False


async def test_put_saves_bumps_the_version_and_refuses_stale_edits(client: AsyncClient) -> None:
    project_id = await project_with_documents(client)
    url = f"/projects/{project_id}/documents"
    saved = (await client.get(url)).json()
    assert saved["version"] == 1
    assert [t["id"] for t in saved["templates"]] == [
        "invoice",
        "receipt",
        "certificate",
        "ticket_summary",
    ]
    ok = await client.put(url, json={**saved, "expected_version": 1, "rate_limit": "10/minute"})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = await client.put(url, json={**saved, "expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"
    duplicate = await client.put(url, json={"templates": [invoice_template(), invoice_template()]})
    assert duplicate.status_code == 422


async def test_the_block_travels_with_the_spec_and_generation_follows_it(
    client: AsyncClient,
) -> None:
    project_id = await project_with_documents(client)
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    assert len(exported["documents"]["templates"]) == 4
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"app/documents/engine.py", "app/documents/router.py", "docs/DOCUMENTS.md"} <= paths

    saved = (await client.get(f"/projects/{project_id}/documents")).json()
    await client.put(f"/projects/{project_id}/documents", json={**saved, "enabled": False})
    off = {
        f["path"]
        for f in (await client.post(f"/projects/{project_id}/generate/preview")).json()["files"]
    }
    assert not any("documents" in p for p in off)


@pytest.mark.parametrize(
    ("change", "path", "code"),
    [
        (lambda t: t.update(id="Bad Id"), "documents.templates[0].id", "invalid_value"),
        (lambda t: t.update(roles=[]), "documents.templates[0].roles", "documents.no_roles"),
        (lambda t: t.update(roles=["ghost"]), "documents.templates[0].roles", "unknown_role"),
        (
            lambda t: t.update(entity="Nope"),
            "documents.templates[0].entity",
            "unknown_entity",
        ),
        (lambda t: t.update(compute="a b"), "documents.templates[0].compute", "invalid_value"),
        (
            lambda t: t.update(template={"blocks": []}),
            "documents.templates[0].template",
            "documents.template",
        ),
    ],
)
async def test_issues_explain_what_is_wrong(
    client: AsyncClient, change: Any, path: str, code: str
) -> None:
    project_id = await project_with_documents(client)
    saved = (await client.get(f"/projects/{project_id}/documents")).json()
    template = copy.deepcopy(saved["templates"][0])
    change(template)
    saved["templates"][0] = template
    assert (await client.put(f"/projects/{project_id}/documents", json=saved)).status_code == 200
    issues = (await client.get(f"/projects/{project_id}/documents/issues")).json()["issues"]
    assert (path, code) in [(i["path"], i["code"]) for i in issues]
    assert (await client.post(f"/projects/{project_id}/validate")).json()["valid"] is False


async def test_a_bound_template_may_only_read_fields_the_entity_has(client: AsyncClient) -> None:
    project_id = await project_with_documents(client)
    saved = (await client.get(f"/projects/{project_id}/documents")).json()
    bound = next(t for t in saved["templates"] if t["entity"] == "Ticket")
    bound["template"]["blocks"][1]["rows"][0]["value"] = "{{row.no_such_field}}"
    await client.put(f"/projects/{project_id}/documents", json=saved)
    issues = (await client.get(f"/projects/{project_id}/documents/issues")).json()["issues"]
    assert "documents.unknown_field" in [i["code"] for i in issues]


async def test_documents_need_sign_in_to_be_switched_on(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/documents", json={"templates": [invoice_template()]})
    issues = (await client.get(f"/projects/{project_id}/documents/issues")).json()["issues"]
    assert "documents.needs_auth" in [i["code"] for i in issues]


# -- who may call what ------------------------------------------------------------------------


async def test_roles_and_isolation(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    stranger = await client_for("stranger@example.com")
    project_id = await make_project(owner)
    await add_to_project_org(project_id, "viewer@example.com")
    added = await owner.post(
        f"/projects/{project_id}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201
    base = f"/projects/{project_id}/documents"
    preview = {"template": {"blocks": [{"type": "paragraph", "text": "hi"}]}}
    assert (await viewer.get(base)).status_code == 200
    assert (await viewer.get(f"{base}/library")).status_code == 200
    assert (await viewer.post(f"{base}/preview", json=preview)).status_code == 200  # computes only
    assert (await viewer.put(base, json={})).status_code == 403
    for call in (
        stranger.get(base),
        stranger.get(f"{base}/library"),
        stranger.post(f"{base}/preview", json=preview),
        stranger.put(base, json={}),
    ):
        assert (await call).status_code == 404
