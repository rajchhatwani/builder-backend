"""Payload factories for the smoke tests (generated). Creates required parents on demand."""
import datetime as _dt
import random as _random
import string as _string
import typing as _t
import uuid as _uuid

from httpx import AsyncClient


def _token(length: int) -> str:
    return "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=length))


def sample_articles() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "handle": _token(12),
        "author": _token(12),
        "body_html": "sample text " + _token(6),
        "summary_html": "sample text " + _token(6),
        "published": True,
        "published_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "tags_cache": {"key": "value"},
    }


async def payload_articles(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_articles()
    if "blog_id" not in overrides:
        payload["blog_id"] = (await make_blogs(client))["id"]
    payload.update(overrides)
    return payload


async def make_articles(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/articles", json=await payload_articles(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_blogs() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "handle": _token(12),
        "commentable": True,
    }


async def payload_blogs(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_blogs()
    payload.update(overrides)
    return payload


async def make_blogs(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/blogs", json=await payload_blogs(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_cart_lines() -> dict[str, _t.Any]:
    return {
        "quantity": _random.randint(1, 10000),
        "properties": {"key": "value"},
    }


async def payload_cart_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_cart_lines()
    if "cart_id" not in overrides:
        payload["cart_id"] = (await make_carts(client))["id"]
    if "variant_id" not in overrides:
        payload["variant_id"] = (await make_variants(client))["id"]
    payload.update(overrides)
    return payload


async def make_cart_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/cart_lines", json=await payload_cart_lines(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_carts() -> dict[str, _t.Any]:
    return {
        "token": _token(12),
        "email": _token(12),
        "currency": _token(3),
        "status": 'open',
        "discount_code": _token(12),
        "note": "sample text " + _token(6),
        "attributes": {"key": "value"},
        "expires_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
    }


async def payload_carts(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_carts()
    payload.update(overrides)
    return payload


async def make_carts(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/carts", json=await payload_carts(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_collections() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "handle": _token(12),
        "description_html": "sample text " + _token(6),
        "kind": 'manual',
        "rules": {"key": "value"},
        "sort_order": 'manual',
        "published": True,
        "published_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "seo_title": _token(12),
        "seo_description": _token(12),
    }


async def payload_collections(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_collections()
    payload.update(overrides)
    return payload


async def make_collections(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/collections", json=await payload_collections(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_customer_addresses() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "company": _token(12),
        "address1": _token(12),
        "address2": _token(12),
        "city": _token(12),
        "province": _token(12),
        "province_code": _token(10),
        "country": _token(12),
        "country_code": _token(2),
        "postal_code": _token(12),
        "phone": _token(12),
        "is_default": True,
    }


async def payload_customer_addresses(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_customer_addresses()
    if "customer_id" not in overrides:
        payload["customer_id"] = (await make_customers(client))["id"]
    payload.update(overrides)
    return payload


async def make_customer_addresses(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/customer_addresses", json=await payload_customer_addresses(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_customers() -> dict[str, _t.Any]:
    return {
        "email": _token(12),
        "first_name": _token(12),
        "last_name": _token(12),
        "phone": _token(12),
        "state": 'enabled',
        "accepts_marketing": True,
        "accepts_marketing_updated_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "tax_exempt": True,
        "total_spent": str(round(_random.uniform(0, 1000), 2)),
        "orders_count": _random.randint(0, 1000),
        "tags_cache": {"key": "value"},
        "note": "sample text " + _token(6),
        "locale": _token(10),
    }


async def payload_customers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_customers()
    payload.update(overrides)
    return payload


async def make_customers(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/customers", json=await payload_customers(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_discount_usages() -> dict[str, _t.Any]:
    return {
        "amount": str(round(_random.uniform(0, 1000), 2)),
        "email": _token(12),
    }


async def payload_discount_usages(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_discount_usages()
    if "discount_id" not in overrides:
        payload["discount_id"] = (await make_discounts(client))["id"]
    if "order_id" not in overrides:
        payload["order_id"] = (await make_orders(client))["id"]
    payload.update(overrides)
    return payload


async def make_discount_usages(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/discount_usages", json=await payload_discount_usages(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_discounts() -> dict[str, _t.Any]:
    return {
        "code": _token(12),
        "title": _token(12),
        "kind": 'percentage',
        "value": str(round(_random.uniform(0, 1000), 2)),
        "target": 'order',
        "minimum_subtotal": str(round(_random.uniform(0, 1000), 2)),
        "usage_limit": _random.randint(1, 1001),
        "once_per_customer": True,
        "used_count": _random.randint(0, 1000),
        "combines_with_other": True,
        "applies_to": {"key": "value"},
        "starts_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "ends_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "active": True,
    }


async def payload_discounts(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_discounts()
    payload.update(overrides)
    return payload


async def make_discounts(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/discounts", json=await payload_discounts(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_fulfillment_lines() -> dict[str, _t.Any]:
    return {
        "quantity": _random.randint(1, 1001),
    }


async def payload_fulfillment_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_fulfillment_lines()
    if "fulfillment_id" not in overrides:
        payload["fulfillment_id"] = (await make_fulfillments(client))["id"]
    if "order_line_id" not in overrides:
        payload["order_line_id"] = (await make_order_lines(client))["id"]
    payload.update(overrides)
    return payload


async def make_fulfillment_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/fulfillment_lines", json=await payload_fulfillment_lines(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_fulfillments() -> dict[str, _t.Any]:
    return {
        "status": 'pending',
        "tracking_company": _token(12),
        "tracking_number": _token(12),
        "tracking_url": _token(12),
        "notify_customer": True,
        "shipped_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
    }


async def payload_fulfillments(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_fulfillments()
    if "order_id" not in overrides:
        payload["order_id"] = (await make_orders(client))["id"]
    payload.update(overrides)
    return payload


async def make_fulfillments(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/fulfillments", json=await payload_fulfillments(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_gift_cards() -> dict[str, _t.Any]:
    return {
        "code": _token(12),
        "initial_value": str(round(_random.uniform(0, 1000), 2)),
        "balance": str(round(_random.uniform(0, 1000), 2)),
        "currency": _token(3),
        "expires_on": (_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat(),
        "disabled": True,
        "note": "sample text " + _token(6),
    }


async def payload_gift_cards(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_gift_cards()
    payload.update(overrides)
    return payload


async def make_gift_cards(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/gift_cards", json=await payload_gift_cards(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_inventory_levels() -> dict[str, _t.Any]:
    return {
        "available": _random.randint(1, 1001),
        "on_hand": _random.randint(1, 1001),
        "committed": _random.randint(0, 1000),
        "incoming": _random.randint(0, 1000),
    }


async def payload_inventory_levels(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_inventory_levels()
    if "location_id" not in overrides:
        payload["location_id"] = (await make_locations(client))["id"]
    if "variant_id" not in overrides:
        payload["variant_id"] = (await make_variants(client))["id"]
    payload.update(overrides)
    return payload


async def make_inventory_levels(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/inventory_levels", json=await payload_inventory_levels(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_locations() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "active": True,
        "fulfills_online_orders": True,
        "address1": _token(12),
        "address2": _token(12),
        "city": _token(12),
        "province": _token(12),
        "province_code": _token(10),
        "country": _token(12),
        "country_code": _token(2),
        "postal_code": _token(12),
        "phone": _token(12),
    }


async def payload_locations(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_locations()
    payload.update(overrides)
    return payload


async def make_locations(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/locations", json=await payload_locations(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_metafields() -> dict[str, _t.Any]:
    return {
        "owner_type": _token(12),
        "owner_id": str(_uuid.uuid4()),
        "namespace": _token(12),
        "key": _token(12),
        "value_type": 'string',
        "value": {"key": "value"},
    }


async def payload_metafields(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_metafields()
    payload.update(overrides)
    return payload


async def make_metafields(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/metafields", json=await payload_metafields(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_order_events() -> dict[str, _t.Any]:
    return {
        "verb": 'placed',
        "message": "sample text " + _token(6),
        "actor": _token(12),
        "data": {"key": "value"},
    }


async def payload_order_events(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_order_events()
    if "order_id" not in overrides:
        payload["order_id"] = (await make_orders(client))["id"]
    payload.update(overrides)
    return payload


async def make_order_events(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/order_events", json=await payload_order_events(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_order_lines() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "variant_title": _token(12),
        "sku": _token(12),
        "quantity": _random.randint(1, 1001),
        "unit_price": str(round(_random.uniform(0, 1000), 2)),
        "discount_total": str(round(_random.uniform(0, 1000), 2)),
        "tax_total": str(round(_random.uniform(0, 1000), 2)),
        "fulfilled_quantity": _random.randint(0, 1000),
        "refunded_quantity": _random.randint(0, 1000),
        "properties": {"key": "value"},
    }


async def payload_order_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_order_lines()
    if "order_id" not in overrides:
        payload["order_id"] = (await make_orders(client))["id"]
    payload.update(overrides)
    return payload


async def make_order_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/order_lines", json=await payload_order_lines(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_orders() -> dict[str, _t.Any]:
    return {
        "number": _random.randint(1, 1001),
        "email": _token(12),
        "status": 'open',
        "financial_status": 'pending',
        "fulfillment_status": 'unfulfilled',
        "currency": _token(3),
        "subtotal": str(round(_random.uniform(0, 1000), 2)),
        "shipping_total": str(round(_random.uniform(0, 1000), 2)),
        "tax_total": str(round(_random.uniform(0, 1000), 2)),
        "discount_total": str(round(_random.uniform(0, 1000), 2)),
        "total": str(round(_random.uniform(0, 1000), 2)),
        "total_refunded": str(round(_random.uniform(0, 1000), 2)),
        "billing_address": {"key": "value"},
        "shipping_address": {"key": "value"},
        "shipping_method": _token(12),
        "discount_code": _token(12),
        "note": "sample text " + _token(6),
        "tags_cache": {"key": "value"},
        "source": _token(12),
        "placed_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "closed_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "cancelled_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "cancel_reason": 'customer',
    }


async def payload_orders(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_orders()
    payload.update(overrides)
    return payload


async def make_orders(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/orders", json=await payload_orders(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_pages() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "handle": _token(12),
        "body_html": "sample text " + _token(6),
        "published": True,
        "template_suffix": _token(12),
    }


async def payload_pages(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_pages()
    payload.update(overrides)
    return payload


async def make_pages(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/pages", json=await payload_pages(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_product_images() -> dict[str, _t.Any]:
    return {
        "url": _token(12),
        "alt": _token(12),
        "position": _random.randint(1, 1001),
        "width": _random.randint(1, 1001),
        "height": _random.randint(1, 1001),
    }


async def payload_product_images(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_product_images()
    if "product_id" not in overrides:
        payload["product_id"] = (await make_products(client))["id"]
    payload.update(overrides)
    return payload


async def make_product_images(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/product_images", json=await payload_product_images(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_products() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "handle": _token(12),
        "description_html": "sample text " + _token(6),
        "vendor": _token(12),
        "product_type": _token(12),
        "status": 'draft',
        "tags_cache": {"key": "value"},
        "options": {"key": "value"},
        "published_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
        "seo_title": _token(12),
        "seo_description": _token(12),
        "requires_shipping": True,
        "taxable": True,
    }


async def payload_products(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_products()
    payload.update(overrides)
    return payload


async def make_products(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/products", json=await payload_products(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_refund_lines() -> dict[str, _t.Any]:
    return {
        "quantity": _random.randint(1, 1001),
        "subtotal": str(round(_random.uniform(0, 1000), 2)),
    }


async def payload_refund_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_refund_lines()
    if "order_line_id" not in overrides:
        payload["order_line_id"] = (await make_order_lines(client))["id"]
    if "refund_id" not in overrides:
        payload["refund_id"] = (await make_refunds(client))["id"]
    payload.update(overrides)
    return payload


async def make_refund_lines(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/refund_lines", json=await payload_refund_lines(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_refunds() -> dict[str, _t.Any]:
    return {
        "amount": str(round(_random.uniform(0, 1000), 2)),
        "reason": _token(12),
        "restock": True,
        "note": "sample text " + _token(6),
    }


async def payload_refunds(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_refunds()
    if "order_id" not in overrides:
        payload["order_id"] = (await make_orders(client))["id"]
    payload.update(overrides)
    return payload


async def make_refunds(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/refunds", json=await payload_refunds(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_reviews() -> dict[str, _t.Any]:
    return {
        "rating": _random.randint(1, 5),
        "title": _token(12),
        "body": "sample text " + _token(6),
        "author_name": _token(12),
        "status": 'pending',
        "verified_purchase": True,
    }


async def payload_reviews(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_reviews()
    if "product_id" not in overrides:
        payload["product_id"] = (await make_products(client))["id"]
    payload.update(overrides)
    return payload


async def make_reviews(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/reviews", json=await payload_reviews(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_shipping_rates() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "price": str(round(_random.uniform(0, 1000), 2)),
        "min_order_subtotal": str(round(_random.uniform(0, 1000), 2)),
        "min_weight": round(_random.uniform(0, 1000), 2),
        "max_weight": round(_random.uniform(0, 1000), 2),
        "active": True,
    }


async def payload_shipping_rates(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_shipping_rates()
    if "zone_id" not in overrides:
        payload["zone_id"] = (await make_shipping_zones(client))["id"]
    payload.update(overrides)
    return payload


async def make_shipping_rates(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/shipping_rates", json=await payload_shipping_rates(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_shipping_zones() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "countries": {"key": "value"},
    }


async def payload_shipping_zones(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_shipping_zones()
    payload.update(overrides)
    return payload


async def make_shipping_zones(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/shipping_zones", json=await payload_shipping_zones(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_stores() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
        "legal_name": _token(12),
        "email": _token(12),
        "domain": _token(12),
        "currency": _token(3),
        "timezone": _token(12),
        "weight_unit": 'kg',
        "plan": 'trial',
        "password_protected": True,
        "settings": {"key": "value"},
    }


async def payload_stores(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_stores()
    payload.update(overrides)
    return payload


async def make_stores(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/stores", json=await payload_stores(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_tags() -> dict[str, _t.Any]:
    return {
        "name": _token(12),
    }


async def payload_tags(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_tags()
    payload.update(overrides)
    return payload


async def make_tags(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/tags", json=await payload_tags(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_tax_rates() -> dict[str, _t.Any]:
    return {
        "country_code": _token(2),
        "province_code": _token(10),
        "name": _token(12),
        "rate": str(round(_random.uniform(0, 1), 2)),
        "includes_shipping": True,
    }


async def payload_tax_rates(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_tax_rates()
    payload.update(overrides)
    return payload


async def make_tax_rates(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/tax_rates", json=await payload_tax_rates(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_transactions() -> dict[str, _t.Any]:
    return {
        "kind": 'authorization',
        "status": 'pending',
        "amount": str(round(_random.uniform(0, 1000), 2)),
        "currency": _token(3),
        "gateway": _token(12),
        "reference": _token(12),
        "error_code": _token(12),
        "processed_at": (_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC) + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat(),
    }


async def payload_transactions(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_transactions()
    if "order_id" not in overrides:
        payload["order_id"] = (await make_orders(client))["id"]
    payload.update(overrides)
    return payload


async def make_transactions(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/transactions", json=await payload_transactions(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_variants() -> dict[str, _t.Any]:
    return {
        "title": _token(12),
        "sku": _token(12),
        "barcode": _token(12),
        "price": str(round(_random.uniform(0, 1000), 2)),
        "compare_at_price": str(round(_random.uniform(0, 1000), 2)),
        "cost": str(round(_random.uniform(0, 1000), 2)),
        "weight": round(_random.uniform(0, 1000), 2),
        "position": _random.randint(1, 1001),
        "option1": _token(12),
        "option2": _token(12),
        "option3": _token(12),
        "taxable": True,
        "requires_shipping": True,
        "inventory_policy": 'deny',
        "inventory_tracked": True,
    }


async def payload_variants(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_variants()
    if "product_id" not in overrides:
        payload["product_id"] = (await make_products(client))["id"]
    payload.update(overrides)
    return payload


async def make_variants(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/variants", json=await payload_variants(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created


def sample_webhooks() -> dict[str, _t.Any]:
    return {
        "topic": 'orders.create',
        "url": _token(12),
        "body_format": 'json',
        "secret": _token(12),
        "active": True,
    }


async def payload_webhooks(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    payload = sample_webhooks()
    payload.update(overrides)
    return payload


async def make_webhooks(client: AsyncClient, **overrides: _t.Any) -> dict[str, _t.Any]:
    response = await client.post(
        "/webhooks", json=await payload_webhooks(client, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, _t.Any] = response.json()
    return created
