"""Access-control tests for the entity routes (generated). Roles and row rules come from the
permissions in the spec; each test names the rule it checks."""

import uuid

import pytest
from httpx import AsyncClient

# The `outbox` fixture (tests/_auth_support.py) sets the test secrets and captures mail / SMS.
pytestmark = pytest.mark.usefixtures("outbox")


def _call(client: AsyncClient, op: str, path: str):  # type: ignore[no-untyped-def]
    """One request per operation. Ids are random and bodies empty: access is decided before
    either is looked at, so a refusal is the only possible answer."""
    missing = uuid.uuid4()
    match op:
        case "list":
            return client.get(f"/{path}")
        case "get":
            return client.get(f"/{path}/{missing}")
        case "head":
            return client.head(f"/{path}/{missing}")
        case "create":
            return client.post(f"/{path}", json={})
        case "replace":
            return client.put(f"/{path}/{missing}", json={})
        case "update":
            return client.patch(f"/{path}/{missing}", json={})
        case _:
            return client.delete(f"/{path}/{missing}")


async def test_orders_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "orders")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"
