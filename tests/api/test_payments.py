"""The payments settings API, its guarded switch, the sizing endpoint and the spec round trip."""

from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_auth, make_project
from tests.unit.test_payments_validation import base_spec


def settings(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "provider": "stripe",
        "currencies": ["USD"],
        "success_urls": ["https://shop.example.com/paid"],
        "cancel_urls": ["https://shop.example.com/cart"],
        "roles": {"create": ["customer"], "read": ["customer"]},
    }
    body.update(overrides)
    return body


async def enable(client: AsyncClient, project_id: str, confirm: bool = True) -> Any:
    return await client.post(f"/projects/{project_id}/payments/enable", json={"confirm": confirm})


async def disable(client: AsyncClient, project_id: str, confirm: bool = True) -> Any:
    return await client.post(f"/projects/{project_id}/payments/disable", json={"confirm": confirm})


async def test_settings_start_empty(client: AsyncClient) -> None:
    project_id = await make_project(client)
    assert (await client.get(f"/projects/{project_id}/payments")).status_code == 404


async def test_put_creates_settings_with_defaults_and_does_not_switch_payments_on(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)

    response = await client.put(f"/projects/{project_id}/payments", json=settings())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["provider"] == "stripe"
    assert body["max_amount_minor"] == 10_000_000
    assert body["security"]["webhook_tolerance_seconds"] == 300
    assert body["security"]["audit_retention_days"] == 2555
    assert body["scale"]["profile"] == "small"
    assert body["roles"]["refund"] == []  # nobody unless listed


async def test_put_replaces_and_get_returns_it(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/payments", json=settings())

    await client.put(
        f"/projects/{project_id}/payments",
        json=settings(
            currencies=["INR"],
            provider="razorpay",
            scale={"profile": "large", "availability": "ha", "kubernetes": True},
        ),
    )

    got = (await client.get(f"/projects/{project_id}/payments")).json()
    assert got["currencies"] == ["INR"]
    assert got["provider"] == "razorpay"
    assert got["scale"]["profile"] == "large"
    assert got["scale"]["kubernetes"] is True


async def test_put_rejects_wrong_shapes(client: AsyncClient) -> None:
    project_id = await make_project(client)
    for bad in (
        {"provider": "venmo"},
        {"max_amount_minor": 0},
        {"scale": {"profile": "huge"}},
        {"scale": {"db_max_connections": 1}},
        {"currencies": ["USD"] * 31},
        {"security": {"webhook_tolerance_seconds": 0}},
    ):
        response = await client.put(f"/projects/{project_id}/payments", json=settings(**bad))
        assert response.status_code == 422, bad


async def test_there_is_no_field_that_could_hold_a_provider_secret(client: AsyncClient) -> None:
    project_id = await make_project(client)
    for key in ("secret_key", "api_key", "webhook_secret", "STRIPE_SECRET_KEY"):
        response = await client.put(
            f"/projects/{project_id}/payments", json=settings(**{key: "sk_test_123"})
        )
        # Unknown fields are ignored by the schema, and must never be echoed back or stored.
        assert response.status_code == 200
        assert "sk_test_123" not in response.text
    stored = (await client.get(f"/projects/{project_id}/payments")).text
    assert "sk_test" not in stored
    exported = (await client.get(f"/projects/{project_id}/spec")).text
    assert "sk_test" not in exported


async def test_unknown_project_is_404(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/projects/{missing}/payments")).status_code == 404
    assert (await client.put(f"/projects/{missing}/payments", json=settings())).status_code == 404


# --- the switch ---------------------------------------------------------------------------


async def test_enable_needs_confirmation_settings_and_auth(client: AsyncClient) -> None:
    project_id = await make_project(client)

    unconfirmed = await enable(client, project_id, confirm=False)
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["code"] == "confirmation_required"

    no_settings = await enable(client, project_id)
    assert no_settings.status_code == 409
    assert "Save the payments settings" in no_settings.json()["message"]

    await client.put(f"/projects/{project_id}/payments", json=settings())
    no_auth = await enable(client, project_id)
    assert no_auth.status_code == 409
    assert "authentication" in no_auth.json()["message"]

    await make_auth(client, project_id)
    ok = await enable(client, project_id)
    assert ok.status_code == 200, ok.text
    assert ok.json()["enabled"] is True


async def test_impact_reports_before_anything_changes(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/payments", json=settings())
    await make_auth(client, project_id)

    impact = (await client.get(f"/projects/{project_id}/payments/impact?action=enable")).json()
    assert impact["can_proceed"] is True
    assert impact["enabled"] is False
    assert any("environment variables" in w for w in impact["warnings"])

    await enable(client, project_id)
    again = (await client.get(f"/projects/{project_id}/payments/impact?action=enable")).json()
    assert again["can_proceed"] is False

    off = (await client.get(f"/projects/{project_id}/payments/impact?action=disable")).json()
    assert off["can_proceed"] is True
    assert any("never dropped" in w for w in off["warnings"])

    bad = await client.get(f"/projects/{project_id}/payments/impact?action=explode")
    assert bad.status_code == 422


async def test_disable_keeps_the_settings_and_saving_does_not_flip_the_switch(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/payments", json=settings(currencies=["EUR"]))
    await make_auth(client, project_id)
    await enable(client, project_id)

    # Saving again while payments are on leaves them on.
    saved = await client.put(f"/projects/{project_id}/payments", json=settings(currencies=["EUR"]))
    assert saved.json()["enabled"] is True

    assert (await disable(client, project_id, confirm=False)).status_code == 422
    off = await disable(client, project_id)
    assert off.status_code == 200
    assert off.json()["enabled"] is False
    assert off.json()["currencies"] == ["EUR"]

    assert (await disable(client, project_id)).status_code == 409  # already off


# --- sizing ---------------------------------------------------------------------------------


async def test_sizing_derives_the_deployment_shape_and_lists_payments_issues(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await client.put(
        f"/projects/{project_id}/payments",
        json=settings(scale={"profile": "large", "availability": "ha", "db_max_connections": 40}),
    )

    body = (await client.get(f"/projects/{project_id}/payments/sizing")).json()

    sizing = body["sizing"]
    assert sizing["payments_per_minute"] == 1200
    assert sizing["webhook_mode"] == "queued"
    assert sizing["api_replicas"] >= 2
    assert sizing["needs_pgbouncer"] is True
    assert sizing["assumptions"], "the numbers are labelled as estimates"
    assert body["issues"] == []  # block is saved but switched off: no rule applies yet

    await make_auth(client, project_id)
    await enable(client, project_id)
    issues = (await client.get(f"/projects/{project_id}/payments/sizing")).json()["issues"]
    assert all(i["path"].startswith("payments") for i in issues)
    assert any(i["code"] == "connection_budget" for i in issues)
    assert any(i["code"] == "required" and i["path"] == "payments.payable" for i in issues)


async def test_sizing_without_settings_is_404(client: AsyncClient) -> None:
    project_id = await make_project(client)
    assert (await client.get(f"/projects/{project_id}/payments/sizing")).status_code == 404


# --- spec round trip --------------------------------------------------------------------------


async def test_payments_survive_a_spec_round_trip_into_another_project(
    client: AsyncClient,
) -> None:
    first = await make_project(client, "First")
    imported = await client.put(f"/projects/{first}/spec", json=base_spec())
    assert imported.status_code == 200, imported.text
    exported = (await client.get(f"/projects/{first}/spec")).json()
    assert exported["payments"]["enabled"] is True
    assert exported["payments"]["payable"]["entity"] == "Order"

    second = await make_project(client, "Second")
    copied = await client.put(f"/projects/{second}/spec", json=exported)
    assert copied.status_code == 200, copied.text
    again = (await client.get(f"/projects/{second}/spec")).json()
    assert again["payments"] == exported["payments"]
    # The row behind it is the same one the payments API serves.
    row = (await client.get(f"/projects/{second}/payments")).json()
    assert row["enabled"] is True
    assert row["roles"]["create"] == ["customer"]


async def test_an_invalid_payments_block_is_refused_and_changes_nothing(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    data = base_spec()
    data["payments"]["currencies"] = []
    refused = await client.put(f"/projects/{project_id}/spec", json=data)
    assert refused.status_code == 422
    assert any(d["path"] == "payments.currencies" for d in refused.json()["details"])
    assert (await client.get(f"/projects/{project_id}/payments")).status_code == 404


async def test_validate_endpoint_reports_payments_problems(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=base_spec())  # payments already on
    await client.put(
        f"/projects/{project_id}/payments",
        json=settings(success_urls=["http://insecure.example.com/"]),
    )
    result = (await client.post(f"/projects/{project_id}/validate")).json()
    issues = result["issues"] if isinstance(result, dict) else result
    assert any(i["path"].startswith("payments.success_urls") for i in issues)
