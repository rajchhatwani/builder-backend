"""POST /projects/{id}/behavior/expressions/check: live expression feedback for the Rules editor."""

import json
import random
import string
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def invoice_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "flow_invoices.json").read_text(encoding="utf-8"))
    return spec


async def project_with_invoice(client: AsyncClient) -> str:
    project_id = await make_project(client)
    assert (await client.put(f"/projects/{project_id}/spec", json=invoice_spec())).status_code == 200
    return project_id


def url(project_id: str) -> str:
    return f"/projects/{project_id}/behavior/expressions/check"


async def check(client: AsyncClient, project_id: str, expression: str, **extra: Any) -> dict[str, Any]:
    r = await client.post(url(project_id), json={"entity": "Invoice", "expression": expression, **extra})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def test_a_good_guard_is_ok_and_lists_the_fields(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    body = await check(client, project_id, "amount > 100 and status == 'draft'")
    assert body["ok"] is True and body["type"] == "bool" and body["error"] is None
    names = {f["name"]: f for f in body["fields"]}
    assert names["amount"] == {"name": "amount", "type": "decimal", "nullable": False}
    assert names["status"]["type"] == "string" and "invoice_no" in names


async def test_bad_expressions_report_message_and_position(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    unknown = await check(client, project_id, "nope > 1")
    assert unknown["ok"] is False and unknown["type"] is None
    assert "unknown field 'nope'" in unknown["error"]["message"]
    assert isinstance(unknown["error"]["pos"], int) and unknown["fields"]
    syntax = await check(client, project_id, "amount +")
    assert syntax["ok"] is False and syntax["error"]["message"]


async def test_expect_bool_refuses_a_number_but_any_accepts_it(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    strict = await check(client, project_id, "amount + 1")
    assert strict["ok"] is False and strict["type"] == "decimal"
    assert strict["error"]["message"] == "a guard must give true or false, not decimal"
    loose = await check(client, project_id, "amount + 1", expect="any")
    assert loose["ok"] is True and loose["type"] == "decimal"


async def test_the_message_is_exactly_the_one_validation_reports(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    for bad in ("nope > 1", "amount +", "amount + 1", "amount > 'x'", "(((", "1 / 0 >"):
        machines = invoice_spec()["state_machines"]
        machines[0]["transitions"][1]["when"] = bad
        saved = await client.put(
            f"/projects/{project_id}/behavior/state-machines", json={"state_machines": machines}
        )
        assert saved.status_code == 200, saved.text
        issues = (await client.post(f"/projects/{project_id}/validate")).json()["issues"]
        guard = [i for i in issues if i["path"].endswith(".when")]
        assert len(guard) == 1, (bad, issues)
        body = await check(client, project_id, bad)
        assert body["ok"] is False
        assert body["error"]["message"] == guard[0]["message"], bad


async def test_too_long_is_refused_by_the_body_limit_not_a_500(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    r = await client.post(url(project_id), json={"entity": "Invoice", "expression": "a" * 1001})
    assert r.status_code == 422
    ok_len = await check(client, project_id, "amount > 1 " + "or amount > 1 " * 0)
    assert ok_len["ok"] is True


async def test_unknown_entity_and_bad_bodies(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    r = await client.post(url(project_id), json={"entity": "Nope", "expression": "true"})
    assert r.status_code == 404
    bad_expect = {"entity": "Invoice", "expression": "true", "expect": "int"}
    assert (await client.post(url(project_id), json=bad_expect)).status_code == 422
    assert (await client.post(url(project_id), json={"entity": "Invoice"})).status_code == 422
    missing = "00000000-0000-4000-8000-000000000000"
    r = await client.post(url(missing), json={"entity": "Invoice", "expression": "true"})
    assert r.status_code == 404


async def test_it_changes_nothing(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    before = (await client.get(f"/projects/{project_id}/spec")).json()
    machines = (await client.get(f"/projects/{project_id}/behavior/state-machines")).json()
    await check(client, project_id, "amount > 1")
    await check(client, project_id, "bad bad")
    assert (await client.get(f"/projects/{project_id}/spec")).json() == before
    after = (await client.get(f"/projects/{project_id}/behavior/state-machines")).json()
    assert after["version"] == machines["version"]


async def test_random_input_never_gives_a_500(client: AsyncClient) -> None:
    project_id = await project_with_invoice(client)
    rng = random.Random(20261101)
    alphabet = string.printable + "éß漢\u0000‮'\"()[]{}<>=!&|+-*/%,. "
    pieces = ["amount", "status", "and", "or", "not", "in", "abs(", "(", ")", "[", "]", "'", "1", "1.5",
              "==", "<=", "+", "-", "*", "/", " ", "null", "true", "invoice_no", "round(", ","]  # fmt: skip
    samples = [
        "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60))) for _ in range(150)
    ] + ["".join(rng.choice(pieces) for _ in range(rng.randint(1, 30))) for _ in range(150)]
    samples += ["(" * 900, "-" * 900, "not " * 240 + "true", "[" * 500, "'" * 999, "\\" * 999]
    for text in samples:
        r = await client.post(url(project_id), json={"entity": "Invoice", "expression": text})
        assert r.status_code in (200, 422), (text[:40], r.status_code, r.text[:200])
        if r.status_code == 200:
            body = r.json()
            assert (body["error"] is None) == body["ok"]


async def test_roles_viewer_ok_stranger_404(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    stranger = await client_for("stranger@example.com")
    project_id = await project_with_invoice(owner)
    await add_to_project_org(project_id, "viewer@example.com")
    added = await owner.post(
        f"/projects/{project_id}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    body = {"entity": "Invoice", "expression": "amount > 1"}
    assert (await viewer.post(url(project_id), json=body)).status_code == 200
    assert (await stranger.post(url(project_id), json=body)).status_code == 404
