"""initial schema

Revision ID: 0001
Revises:
Create Date: rendered from the spec by Backend Builder

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("handle", sa.String(255), nullable=False),
        sa.Column("author", sa.String(120), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("summary_html", sa.Text(), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags_cache", postgresql.JSONB(), nullable=True),
        sa.Column("blog_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_articles"),
    )
    op.create_index("ix_articles_blog_id", "articles", ["blog_id"])
    op.create_index("ix_articles_handle", "articles", ["handle"])
    op.create_table(
        "blogs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("handle", sa.String(200), nullable=False),
        sa.Column("commentable", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_blogs"),
    )
    op.create_index("ix_blogs_handle", "blogs", ["handle"])
    op.create_table(
        "cart_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.Column("cart_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_cart_lines"),
    )
    op.create_index("ix_cart_lines_cart_id", "cart_lines", ["cart_id"])
    op.create_index("ix_cart_lines_variant_id", "cart_lines", ["variant_id"])
    op.create_table(
        "carts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("discount_code", sa.String(64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_carts"),
        sa.UniqueConstraint("token", name="uq_carts_token"),
    )
    op.create_index("ix_carts_customer_id", "carts", ["customer_id"])
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("handle", sa.String(200), nullable=False),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column("rules", postgresql.JSONB(), nullable=True),
        sa.Column("sort_order", sa.String(64), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seo_title", sa.String(70), nullable=True),
        sa.Column("seo_description", sa.String(320), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_collections"),
    )
    op.create_index("ix_collections_handle", "collections", ["handle"])
    op.create_index("ix_collections_parent_id", "collections", ["parent_id"])
    op.create_table(
        "customer_addresses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("company", sa.String(120), nullable=True),
        sa.Column("address1", sa.String(200), nullable=False),
        sa.Column("address2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("province", sa.String(100), nullable=True),
        sa.Column("province_code", sa.String(10), nullable=True),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_customer_addresses"),
    )
    op.create_index("ix_customer_addresses_customer_id", "customer_addresses", ["customer_id"])
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("accepts_marketing", sa.Boolean(), nullable=True),
        sa.Column("accepts_marketing_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tax_exempt", sa.Boolean(), nullable=True),
        sa.Column("total_spent", sa.Numeric(18, 6), nullable=True),
        sa.Column("orders_count", sa.Integer(), nullable=True),
        sa.Column("tags_cache", postgresql.JSONB(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("locale", sa.String(10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
    )
    op.create_index("ix_customers_email", "customers", ["email"])
    op.create_table(
        "discount_usages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("discount_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_discount_usages"),
    )
    op.create_index("ix_discount_usages_discount_id", "discount_usages", ["discount_id"])
    op.create_index("ix_discount_usages_order_id", "discount_usages", ["order_id"])
    op.create_table(
        "discounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(120), nullable=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("target", sa.String(64), nullable=True),
        sa.Column("minimum_subtotal", sa.Numeric(18, 6), nullable=True),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("once_per_customer", sa.Boolean(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=True),
        sa.Column("combines_with_other", sa.Boolean(), nullable=True),
        sa.Column("applies_to", postgresql.JSONB(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_discounts"),
        sa.UniqueConstraint("code", name="uq_discounts_code"),
    )
    op.create_table(
        "fulfillment_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("fulfillment_id", sa.Uuid(), nullable=False),
        sa.Column("order_line_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_fulfillment_lines"),
    )
    op.create_index("ix_fulfillment_lines_fulfillment_id", "fulfillment_lines", ["fulfillment_id"])
    op.create_index("ix_fulfillment_lines_order_line_id", "fulfillment_lines", ["order_line_id"])
    op.create_table(
        "fulfillments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("tracking_company", sa.String(120), nullable=True),
        sa.Column("tracking_number", sa.String(120), nullable=True),
        sa.Column("tracking_url", sa.String(2000), nullable=True),
        sa.Column("notify_customer", sa.Boolean(), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_fulfillments"),
    )
    op.create_index("ix_fulfillments_location_id", "fulfillments", ["location_id"])
    op.create_index("ix_fulfillments_order_id", "fulfillments", ["order_id"])
    op.create_index("ix_fulfillments_tracking_number", "fulfillments", ["tracking_number"])
    op.create_table(
        "gift_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("initial_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("balance", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("disabled", sa.Boolean(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_gift_cards"),
        sa.UniqueConstraint("code", name="uq_gift_cards_code"),
    )
    op.create_index("ix_gift_cards_customer_id", "gift_cards", ["customer_id"])
    op.create_table(
        "inventory_levels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False),
        sa.Column("on_hand", sa.Integer(), nullable=True),
        sa.Column("committed", sa.Integer(), nullable=True),
        sa.Column("incoming", sa.Integer(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_inventory_levels"),
    )
    op.create_index("ix_inventory_levels_location_id", "inventory_levels", ["location_id"])
    op.create_index("ix_inventory_levels_variant_id", "inventory_levels", ["variant_id"])
    op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("fulfills_online_orders", sa.Boolean(), nullable=True),
        sa.Column("address1", sa.String(200), nullable=False),
        sa.Column("address2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("province", sa.String(100), nullable=True),
        sa.Column("province_code", sa.String(10), nullable=True),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_locations"),
    )
    op.create_table(
        "metafields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(40), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(60), nullable=False),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value_type", sa.String(64), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_metafields"),
    )
    op.create_index("ix_metafields_owner_id", "metafields", ["owner_id"])
    op.create_index("ix_metafields_owner_type", "metafields", ["owner_type"])
    op.create_table(
        "order_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verb", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(254), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_events"),
    )
    op.create_index("ix_order_events_order_id", "order_events", ["order_id"])
    op.create_table(
        "order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("variant_title", sa.String(255), nullable=True),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("discount_total", sa.Numeric(18, 6), nullable=True),
        sa.Column("tax_total", sa.Numeric(18, 6), nullable=True),
        sa.Column("fulfilled_quantity", sa.Integer(), nullable=True),
        sa.Column("refunded_quantity", sa.Integer(), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_lines"),
    )
    op.create_index("ix_order_lines_order_id", "order_lines", ["order_id"])
    op.create_index("ix_order_lines_variant_id", "order_lines", ["variant_id"])
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("financial_status", sa.String(64), nullable=True),
        sa.Column("fulfillment_status", sa.String(64), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 6), nullable=False),
        sa.Column("shipping_total", sa.Numeric(18, 6), nullable=True),
        sa.Column("tax_total", sa.Numeric(18, 6), nullable=True),
        sa.Column("discount_total", sa.Numeric(18, 6), nullable=True),
        sa.Column("total", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_refunded", sa.Numeric(18, 6), nullable=True),
        sa.Column("billing_address", postgresql.JSONB(), nullable=True),
        sa.Column("shipping_address", postgresql.JSONB(), nullable=True),
        sa.Column("shipping_method", sa.String(120), nullable=True),
        sa.Column("discount_code", sa.String(64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tags_cache", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(60), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(64), nullable=True),
        sa.Column("cart_id", sa.Uuid(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("shipping_rate_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("cart_id", name="uq_orders_cart_id"),
        sa.UniqueConstraint("number", name="uq_orders_number"),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_email", "orders", ["email"])
    op.create_index("ix_orders_shipping_rate_id", "orders", ["shipping_rate_id"])
    op.create_table(
        "pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("handle", sa.String(255), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=True),
        sa.Column("template_suffix", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pages"),
    )
    op.create_index("ix_pages_handle", "pages", ["handle"])
    op.create_table(
        "product_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("alt", sa.String(512), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_product_images"),
    )
    op.create_index("ix_product_images_product_id", "product_images", ["product_id"])
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("handle", sa.String(255), nullable=False),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("vendor", sa.String(120), nullable=True),
        sa.Column("product_type", sa.String(120), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("tags_cache", postgresql.JSONB(), nullable=True),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seo_title", sa.String(70), nullable=True),
        sa.Column("seo_description", sa.String(320), nullable=True),
        sa.Column("requires_shipping", sa.Boolean(), nullable=True),
        sa.Column("taxable", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
    )
    op.create_index("ix_products_handle", "products", ["handle"])
    op.create_index("ix_products_product_type", "products", ["product_type"])
    op.create_index("ix_products_vendor", "products", ["vendor"])
    op.create_table(
        "refund_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 6), nullable=False),
        sa.Column("order_line_id", sa.Uuid(), nullable=False),
        sa.Column("refund_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_refund_lines"),
    )
    op.create_index("ix_refund_lines_order_line_id", "refund_lines", ["order_line_id"])
    op.create_index("ix_refund_lines_refund_id", "refund_lines", ["refund_id"])
    op.create_table(
        "refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("restock", sa.Boolean(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_refunds"),
    )
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("author_name", sa.String(120), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("verified_purchase", sa.Boolean(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
    )
    op.create_index("ix_reviews_customer_id", "reviews", ["customer_id"])
    op.create_index("ix_reviews_product_id", "reviews", ["product_id"])
    op.create_table(
        "shipping_rates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("min_order_subtotal", sa.Numeric(18, 6), nullable=True),
        sa.Column("min_weight", sa.Float(), nullable=True),
        sa.Column("max_weight", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("zone_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shipping_rates"),
    )
    op.create_index("ix_shipping_rates_zone_id", "shipping_rates", ["zone_id"])
    op.create_table(
        "shipping_zones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("countries", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shipping_zones"),
    )
    op.create_table(
        "stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("domain", sa.String(253), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("weight_unit", sa.String(64), nullable=True),
        sa.Column("plan", sa.String(64), nullable=True),
        sa.Column("password_protected", sa.Boolean(), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_stores"),
    )
    op.create_index("ix_stores_domain", "stores", ["domain"])
    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
    )
    op.create_index("ix_tags_name", "tags", ["name"])
    op.create_table(
        "tax_rates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("province_code", sa.String(10), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("includes_shipping", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tax_rates"),
    )
    op.create_index("ix_tax_rates_country_code", "tax_rates", ["country_code"])
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("gateway", sa.String(60), nullable=True),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
    )
    op.create_index("ix_transactions_order_id", "transactions", ["order_id"])
    op.create_index("ix_transactions_reference", "transactions", ["reference"])
    op.create_table(
        "variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("barcode", sa.String(64), nullable=True),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("compare_at_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("cost", sa.Numeric(18, 6), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("option1", sa.String(255), nullable=True),
        sa.Column("option2", sa.String(255), nullable=True),
        sa.Column("option3", sa.String(255), nullable=True),
        sa.Column("taxable", sa.Boolean(), nullable=True),
        sa.Column("requires_shipping", sa.Boolean(), nullable=True),
        sa.Column("inventory_policy", sa.String(64), nullable=True),
        sa.Column("inventory_tracked", sa.Boolean(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_variants"),
        sa.UniqueConstraint("sku", name="uq_variants_sku"),
    )
    op.create_index("ix_variants_barcode", "variants", ["barcode"])
    op.create_index("ix_variants_product_id", "variants", ["product_id"])
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("body_format", sa.String(64), nullable=True),
        sa.Column("secret", sa.String(128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_webhooks"),
    )
    op.create_table(
        "collections_products",
        sa.Column("left_id", sa.Uuid(), nullable=False),
        sa.Column("right_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["left_id"], ["collections.id"], name="fk_collections_products_left_id_collections", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["right_id"], ["products.id"], name="fk_collections_products_right_id_products", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("left_id", "right_id", name="pk_collections_products"),
    )
    op.create_table(
        "products_tags",
        sa.Column("left_id", sa.Uuid(), nullable=False),
        sa.Column("right_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["left_id"], ["products.id"], name="fk_products_tags_left_id_products", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["right_id"], ["tags.id"], name="fk_products_tags_right_id_tags", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("left_id", "right_id", name="pk_products_tags"),
    )
    op.create_foreign_key(
        "fk_articles_blog_id_blogs",
        "articles",
        "blogs",
        ["blog_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_cart_lines_cart_id_carts",
        "cart_lines",
        "carts",
        ["cart_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_cart_lines_variant_id_variants",
        "cart_lines",
        "variants",
        ["variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_carts_customer_id_customers",
        "carts",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_collections_parent_id_collections",
        "collections",
        "collections",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_customer_addresses_customer_id_customers",
        "customer_addresses",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_discount_usages_discount_id_discounts",
        "discount_usages",
        "discounts",
        ["discount_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_discount_usages_order_id_orders",
        "discount_usages",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_fulfillment_lines_fulfillment_id_fulfillments",
        "fulfillment_lines",
        "fulfillments",
        ["fulfillment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_fulfillment_lines_order_line_id_order_lines",
        "fulfillment_lines",
        "order_lines",
        ["order_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_fulfillments_location_id_locations",
        "fulfillments",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_fulfillments_order_id_orders",
        "fulfillments",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_gift_cards_customer_id_customers",
        "gift_cards",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inventory_levels_location_id_locations",
        "inventory_levels",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_inventory_levels_variant_id_variants",
        "inventory_levels",
        "variants",
        ["variant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_order_events_order_id_orders",
        "order_events",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_order_lines_order_id_orders",
        "order_lines",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_order_lines_variant_id_variants",
        "order_lines",
        "variants",
        ["variant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_orders_cart_id_carts",
        "orders",
        "carts",
        ["cart_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_orders_customer_id_customers",
        "orders",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_orders_shipping_rate_id_shipping_rates",
        "orders",
        "shipping_rates",
        ["shipping_rate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_product_images_product_id_products",
        "product_images",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_refund_lines_order_line_id_order_lines",
        "refund_lines",
        "order_lines",
        ["order_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_refund_lines_refund_id_refunds",
        "refund_lines",
        "refunds",
        ["refund_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_refunds_order_id_orders",
        "refunds",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reviews_customer_id_customers",
        "reviews",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_reviews_product_id_products",
        "reviews",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_shipping_rates_zone_id_shipping_zones",
        "shipping_rates",
        "shipping_zones",
        ["zone_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_transactions_order_id_orders",
        "transactions",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_variants_product_id_products",
        "variants",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_variants_product_id_products", "variants", type_="foreignkey")
    op.drop_constraint("fk_transactions_order_id_orders", "transactions", type_="foreignkey")
    op.drop_constraint("fk_shipping_rates_zone_id_shipping_zones", "shipping_rates", type_="foreignkey")
    op.drop_constraint("fk_reviews_customer_id_customers", "reviews", type_="foreignkey")
    op.drop_constraint("fk_reviews_product_id_products", "reviews", type_="foreignkey")
    op.drop_constraint("fk_refunds_order_id_orders", "refunds", type_="foreignkey")
    op.drop_constraint("fk_refund_lines_order_line_id_order_lines", "refund_lines", type_="foreignkey")
    op.drop_constraint("fk_refund_lines_refund_id_refunds", "refund_lines", type_="foreignkey")
    op.drop_constraint("fk_product_images_product_id_products", "product_images", type_="foreignkey")
    op.drop_constraint("fk_orders_cart_id_carts", "orders", type_="foreignkey")
    op.drop_constraint("fk_orders_customer_id_customers", "orders", type_="foreignkey")
    op.drop_constraint("fk_orders_shipping_rate_id_shipping_rates", "orders", type_="foreignkey")
    op.drop_constraint("fk_order_lines_order_id_orders", "order_lines", type_="foreignkey")
    op.drop_constraint("fk_order_lines_variant_id_variants", "order_lines", type_="foreignkey")
    op.drop_constraint("fk_order_events_order_id_orders", "order_events", type_="foreignkey")
    op.drop_constraint("fk_inventory_levels_location_id_locations", "inventory_levels", type_="foreignkey")
    op.drop_constraint("fk_inventory_levels_variant_id_variants", "inventory_levels", type_="foreignkey")
    op.drop_constraint("fk_gift_cards_customer_id_customers", "gift_cards", type_="foreignkey")
    op.drop_constraint("fk_fulfillments_location_id_locations", "fulfillments", type_="foreignkey")
    op.drop_constraint("fk_fulfillments_order_id_orders", "fulfillments", type_="foreignkey")
    op.drop_constraint("fk_fulfillment_lines_fulfillment_id_fulfillments", "fulfillment_lines", type_="foreignkey")
    op.drop_constraint("fk_fulfillment_lines_order_line_id_order_lines", "fulfillment_lines", type_="foreignkey")
    op.drop_constraint("fk_discount_usages_discount_id_discounts", "discount_usages", type_="foreignkey")
    op.drop_constraint("fk_discount_usages_order_id_orders", "discount_usages", type_="foreignkey")
    op.drop_constraint("fk_customer_addresses_customer_id_customers", "customer_addresses", type_="foreignkey")
    op.drop_constraint("fk_collections_parent_id_collections", "collections", type_="foreignkey")
    op.drop_constraint("fk_carts_customer_id_customers", "carts", type_="foreignkey")
    op.drop_constraint("fk_cart_lines_cart_id_carts", "cart_lines", type_="foreignkey")
    op.drop_constraint("fk_cart_lines_variant_id_variants", "cart_lines", type_="foreignkey")
    op.drop_constraint("fk_articles_blog_id_blogs", "articles", type_="foreignkey")
    op.drop_table("products_tags")
    op.drop_table("collections_products")
    op.drop_table("webhooks")
    op.drop_table("variants")
    op.drop_table("transactions")
    op.drop_table("tax_rates")
    op.drop_table("tags")
    op.drop_table("stores")
    op.drop_table("shipping_zones")
    op.drop_table("shipping_rates")
    op.drop_table("reviews")
    op.drop_table("refunds")
    op.drop_table("refund_lines")
    op.drop_table("products")
    op.drop_table("product_images")
    op.drop_table("pages")
    op.drop_table("orders")
    op.drop_table("order_lines")
    op.drop_table("order_events")
    op.drop_table("metafields")
    op.drop_table("locations")
    op.drop_table("inventory_levels")
    op.drop_table("gift_cards")
    op.drop_table("fulfillments")
    op.drop_table("fulfillment_lines")
    op.drop_table("discounts")
    op.drop_table("discount_usages")
    op.drop_table("customers")
    op.drop_table("customer_addresses")
    op.drop_table("collections")
    op.drop_table("carts")
    op.drop_table("cart_lines")
    op.drop_table("blogs")
    op.drop_table("articles")
