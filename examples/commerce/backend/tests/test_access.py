"""Access-control tests for the entity routes (generated). Roles and row rules come from the
permissions in the spec; each test names the rule it checks."""

import uuid

import pytest
from httpx import AsyncClient

from tests._auth_support import client_for, sign_in_plain

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


async def test_articles_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "articles")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_articles_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "articles")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_blogs_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "blogs")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_blogs_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "blogs")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_cart_lines_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "cart_lines")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_cart_lines_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "cart_lines")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_carts_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "carts")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_carts_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "carts")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_collections_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "collections")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_collections_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "collections")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_customer_addresses_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "customer_addresses")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_customer_addresses_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "customer_addresses")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_customers_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "customers")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_customers_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "customers")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_discount_usages_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "list"):
        response = await _call(client, op, "discount_usages")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_discount_usages_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "get", "list"):
            response = await _call(plain, op, "discount_usages")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_discounts_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "discounts")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_discounts_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "discounts")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_fulfillment_lines_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "fulfillment_lines")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_fulfillment_lines_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "fulfillment_lines")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_fulfillments_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "fulfillments")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_fulfillments_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "fulfillments")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_gift_cards_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "gift_cards")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_gift_cards_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "gift_cards")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_inventory_levels_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "inventory_levels")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_inventory_levels_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "inventory_levels")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_locations_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "locations")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_locations_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "locations")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_metafields_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "metafields")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_metafields_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "metafields")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_order_events_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "list"):
        response = await _call(client, op, "order_events")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_order_events_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "get", "list"):
            response = await _call(plain, op, "order_events")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_order_lines_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "list", "update"):
        response = await _call(client, op, "order_lines")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_order_lines_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("get", "list", "update"):
            response = await _call(plain, op, "order_lines")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_orders_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "head", "list", "update"):
        response = await _call(client, op, "orders")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_orders_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("get", "head", "list", "update"):
            response = await _call(plain, op, "orders")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_pages_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "pages")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_pages_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "pages")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_product_images_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "product_images")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_product_images_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "product_images")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_products_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "products")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_products_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "products")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_refund_lines_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "list"):
        response = await _call(client, op, "refund_lines")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_refund_lines_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "get", "list"):
            response = await _call(plain, op, "refund_lines")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_refunds_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "list"):
        response = await _call(client, op, "refunds")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_refunds_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "get", "list"):
            response = await _call(plain, op, "refunds")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_reviews_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "list", "update"):
        response = await _call(client, op, "reviews")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_reviews_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("delete", "update"):
            response = await _call(plain, op, "reviews")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_shipping_rates_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "shipping_rates")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_shipping_rates_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "shipping_rates")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_shipping_zones_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "shipping_zones")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_shipping_zones_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "shipping_zones")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_stores_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "list", "update"):
        response = await _call(client, op, "stores")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_stores_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "get", "list", "update"):
            response = await _call(plain, op, "stores")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_tags_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "tags")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_tags_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "tags")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_tax_rates_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "tax_rates")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_tax_rates_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "tax_rates")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_transactions_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "get", "list"):
        response = await _call(client, op, "transactions")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_transactions_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "get", "list"):
            response = await _call(plain, op, "transactions")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_variants_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "variants")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_variants_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "replace", "update"):
            response = await _call(plain, op, "variants")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"


async def test_webhooks_routes_need_a_signed_in_user(client: AsyncClient) -> None:
    for op in ("create", "delete", "get", "head", "list", "replace", "update"):
        response = await _call(client, op, "webhooks")
        assert response.status_code == 401, (op, response.text)
        if op != "head":  # a HEAD response has no body to read the code from
            assert response.json()["code"] == "unauthorized"


async def test_webhooks_routes_reject_users_without_the_required_role(
    client: AsyncClient,
) -> None:
    # A freshly registered user only holds the default role(s).
    async with client_for(await sign_in_plain(client, "plain@example.com")) as plain:
        for op in ("create", "delete", "get", "head", "list", "replace", "update"):
            response = await _call(plain, op, "webhooks")
            assert response.status_code == 403, (op, response.text)
            if op != "head":
                assert response.json()["code"] == "forbidden"
