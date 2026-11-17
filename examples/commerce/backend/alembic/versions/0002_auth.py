"""authentication tables

Revision ID: 0002
Revises: 0001
Create Date: rendered from the spec by Backend Builder

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_tenants"),
    )
    op.create_table(
        "auth_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("roles", postgresql.JSONB(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("job_title", sa.String(80), nullable=True),
        sa.Column("locale", sa.String(64), nullable=True),
        sa.Column("marketing_opt_in", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["auth_tenants.id"],
            name="fk_auth_users_tenant_id_auth_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_users"),
        sa.UniqueConstraint("email", name="uq_auth_users_email"),
        sa.UniqueConstraint("phone", name="uq_auth_users_phone"),
    )
    op.create_index("ix_auth_users_tenant_id", "auth_users", ["tenant_id"])
    op.create_table(
        "auth_verification_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(5), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.id"],
            name="fk_auth_verification_codes_user_id_auth_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_verification_codes"),
    )
    op.create_index("ix_auth_verification_codes_user_id", "auth_verification_codes", ["user_id"])
    op.create_index("ix_auth_verification_codes_code_hash", "auth_verification_codes", ["code_hash"])
    op.create_table(
        "auth_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("roles", postgresql.JSONB(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["invited_by_id"],
            ["auth_users.id"],
            name="fk_auth_invitations_invited_by_id_auth_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["auth_tenants.id"],
            name="fk_auth_invitations_tenant_id_auth_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_invitations"),
        sa.UniqueConstraint("token_hash", name="uq_auth_invitations_token_hash"),
    )
    op.create_index("ix_auth_invitations_email", "auth_invitations", ["email"])
    op.create_index("ix_auth_invitations_tenant_id", "auth_invitations", ["tenant_id"])
    op.create_table(
        "auth_provider_lock",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("realm", sa.String(63), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_provider_lock"),
    )
    op.add_column("articles", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_articles_tenant_id_auth_tenants",
        "articles",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_articles_tenant_id", "articles", ["tenant_id"])
    op.add_column("blogs", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_blogs_tenant_id_auth_tenants",
        "blogs",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_blogs_tenant_id", "blogs", ["tenant_id"])
    op.add_column("cart_lines", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_cart_lines_tenant_id_auth_tenants",
        "cart_lines",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_cart_lines_tenant_id", "cart_lines", ["tenant_id"])
    op.add_column("carts", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_carts_tenant_id_auth_tenants",
        "carts",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_carts_tenant_id", "carts", ["tenant_id"])
    op.add_column("collections", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_collections_tenant_id_auth_tenants",
        "collections",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_collections_tenant_id", "collections", ["tenant_id"])
    op.add_column("customer_addresses", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_customer_addresses_tenant_id_auth_tenants",
        "customer_addresses",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_customer_addresses_tenant_id", "customer_addresses", ["tenant_id"])
    op.add_column("customers", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_customers_tenant_id_auth_tenants",
        "customers",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.add_column("discount_usages", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_discount_usages_tenant_id_auth_tenants",
        "discount_usages",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_discount_usages_tenant_id", "discount_usages", ["tenant_id"])
    op.add_column("discounts", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_discounts_tenant_id_auth_tenants",
        "discounts",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_discounts_tenant_id", "discounts", ["tenant_id"])
    op.add_column("fulfillment_lines", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_fulfillment_lines_tenant_id_auth_tenants",
        "fulfillment_lines",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_fulfillment_lines_tenant_id", "fulfillment_lines", ["tenant_id"])
    op.add_column("fulfillments", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_fulfillments_tenant_id_auth_tenants",
        "fulfillments",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_fulfillments_tenant_id", "fulfillments", ["tenant_id"])
    op.add_column("gift_cards", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_gift_cards_tenant_id_auth_tenants",
        "gift_cards",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_gift_cards_tenant_id", "gift_cards", ["tenant_id"])
    op.add_column("inventory_levels", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_inventory_levels_tenant_id_auth_tenants",
        "inventory_levels",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_inventory_levels_tenant_id", "inventory_levels", ["tenant_id"])
    op.add_column("locations", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_locations_tenant_id_auth_tenants",
        "locations",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_locations_tenant_id", "locations", ["tenant_id"])
    op.add_column("metafields", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_metafields_tenant_id_auth_tenants",
        "metafields",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_metafields_tenant_id", "metafields", ["tenant_id"])
    op.add_column("order_events", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_order_events_tenant_id_auth_tenants",
        "order_events",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_order_events_tenant_id", "order_events", ["tenant_id"])
    op.add_column("order_lines", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_order_lines_tenant_id_auth_tenants",
        "order_lines",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_order_lines_tenant_id", "order_lines", ["tenant_id"])
    op.add_column("orders", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_orders_tenant_id_auth_tenants",
        "orders",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.add_column("pages", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_pages_tenant_id_auth_tenants",
        "pages",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_pages_tenant_id", "pages", ["tenant_id"])
    op.add_column("product_images", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_product_images_tenant_id_auth_tenants",
        "product_images",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_product_images_tenant_id", "product_images", ["tenant_id"])
    op.add_column("products", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_products_tenant_id_auth_tenants",
        "products",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.add_column("refund_lines", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_refund_lines_tenant_id_auth_tenants",
        "refund_lines",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_refund_lines_tenant_id", "refund_lines", ["tenant_id"])
    op.add_column("refunds", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_refunds_tenant_id_auth_tenants",
        "refunds",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_refunds_tenant_id", "refunds", ["tenant_id"])
    op.add_column("reviews", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_reviews_tenant_id_auth_tenants",
        "reviews",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_reviews_tenant_id", "reviews", ["tenant_id"])
    op.add_column("shipping_rates", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_shipping_rates_tenant_id_auth_tenants",
        "shipping_rates",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_shipping_rates_tenant_id", "shipping_rates", ["tenant_id"])
    op.add_column("shipping_zones", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_shipping_zones_tenant_id_auth_tenants",
        "shipping_zones",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_shipping_zones_tenant_id", "shipping_zones", ["tenant_id"])
    op.add_column("stores", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_stores_tenant_id_auth_tenants",
        "stores",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_stores_tenant_id", "stores", ["tenant_id"])
    op.add_column("tags", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tags_tenant_id_auth_tenants",
        "tags",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tags_tenant_id", "tags", ["tenant_id"])
    op.add_column("tax_rates", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tax_rates_tenant_id_auth_tenants",
        "tax_rates",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tax_rates_tenant_id", "tax_rates", ["tenant_id"])
    op.add_column("transactions", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_tenant_id_auth_tenants",
        "transactions",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_transactions_tenant_id", "transactions", ["tenant_id"])
    op.add_column("variants", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_variants_tenant_id_auth_tenants",
        "variants",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_variants_tenant_id", "variants", ["tenant_id"])
    op.add_column("webhooks", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_webhooks_tenant_id_auth_tenants",
        "webhooks",
        "auth_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_webhooks_tenant_id", "webhooks", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_articles_tenant_id", table_name="articles")
    op.drop_constraint("fk_articles_tenant_id_auth_tenants", "articles", type_="foreignkey")
    op.drop_column("articles", "tenant_id")
    op.drop_index("ix_blogs_tenant_id", table_name="blogs")
    op.drop_constraint("fk_blogs_tenant_id_auth_tenants", "blogs", type_="foreignkey")
    op.drop_column("blogs", "tenant_id")
    op.drop_index("ix_cart_lines_tenant_id", table_name="cart_lines")
    op.drop_constraint("fk_cart_lines_tenant_id_auth_tenants", "cart_lines", type_="foreignkey")
    op.drop_column("cart_lines", "tenant_id")
    op.drop_index("ix_carts_tenant_id", table_name="carts")
    op.drop_constraint("fk_carts_tenant_id_auth_tenants", "carts", type_="foreignkey")
    op.drop_column("carts", "tenant_id")
    op.drop_index("ix_collections_tenant_id", table_name="collections")
    op.drop_constraint("fk_collections_tenant_id_auth_tenants", "collections", type_="foreignkey")
    op.drop_column("collections", "tenant_id")
    op.drop_index("ix_customer_addresses_tenant_id", table_name="customer_addresses")
    op.drop_constraint("fk_customer_addresses_tenant_id_auth_tenants", "customer_addresses", type_="foreignkey")
    op.drop_column("customer_addresses", "tenant_id")
    op.drop_index("ix_customers_tenant_id", table_name="customers")
    op.drop_constraint("fk_customers_tenant_id_auth_tenants", "customers", type_="foreignkey")
    op.drop_column("customers", "tenant_id")
    op.drop_index("ix_discount_usages_tenant_id", table_name="discount_usages")
    op.drop_constraint("fk_discount_usages_tenant_id_auth_tenants", "discount_usages", type_="foreignkey")
    op.drop_column("discount_usages", "tenant_id")
    op.drop_index("ix_discounts_tenant_id", table_name="discounts")
    op.drop_constraint("fk_discounts_tenant_id_auth_tenants", "discounts", type_="foreignkey")
    op.drop_column("discounts", "tenant_id")
    op.drop_index("ix_fulfillment_lines_tenant_id", table_name="fulfillment_lines")
    op.drop_constraint("fk_fulfillment_lines_tenant_id_auth_tenants", "fulfillment_lines", type_="foreignkey")
    op.drop_column("fulfillment_lines", "tenant_id")
    op.drop_index("ix_fulfillments_tenant_id", table_name="fulfillments")
    op.drop_constraint("fk_fulfillments_tenant_id_auth_tenants", "fulfillments", type_="foreignkey")
    op.drop_column("fulfillments", "tenant_id")
    op.drop_index("ix_gift_cards_tenant_id", table_name="gift_cards")
    op.drop_constraint("fk_gift_cards_tenant_id_auth_tenants", "gift_cards", type_="foreignkey")
    op.drop_column("gift_cards", "tenant_id")
    op.drop_index("ix_inventory_levels_tenant_id", table_name="inventory_levels")
    op.drop_constraint("fk_inventory_levels_tenant_id_auth_tenants", "inventory_levels", type_="foreignkey")
    op.drop_column("inventory_levels", "tenant_id")
    op.drop_index("ix_locations_tenant_id", table_name="locations")
    op.drop_constraint("fk_locations_tenant_id_auth_tenants", "locations", type_="foreignkey")
    op.drop_column("locations", "tenant_id")
    op.drop_index("ix_metafields_tenant_id", table_name="metafields")
    op.drop_constraint("fk_metafields_tenant_id_auth_tenants", "metafields", type_="foreignkey")
    op.drop_column("metafields", "tenant_id")
    op.drop_index("ix_order_events_tenant_id", table_name="order_events")
    op.drop_constraint("fk_order_events_tenant_id_auth_tenants", "order_events", type_="foreignkey")
    op.drop_column("order_events", "tenant_id")
    op.drop_index("ix_order_lines_tenant_id", table_name="order_lines")
    op.drop_constraint("fk_order_lines_tenant_id_auth_tenants", "order_lines", type_="foreignkey")
    op.drop_column("order_lines", "tenant_id")
    op.drop_index("ix_orders_tenant_id", table_name="orders")
    op.drop_constraint("fk_orders_tenant_id_auth_tenants", "orders", type_="foreignkey")
    op.drop_column("orders", "tenant_id")
    op.drop_index("ix_pages_tenant_id", table_name="pages")
    op.drop_constraint("fk_pages_tenant_id_auth_tenants", "pages", type_="foreignkey")
    op.drop_column("pages", "tenant_id")
    op.drop_index("ix_product_images_tenant_id", table_name="product_images")
    op.drop_constraint("fk_product_images_tenant_id_auth_tenants", "product_images", type_="foreignkey")
    op.drop_column("product_images", "tenant_id")
    op.drop_index("ix_products_tenant_id", table_name="products")
    op.drop_constraint("fk_products_tenant_id_auth_tenants", "products", type_="foreignkey")
    op.drop_column("products", "tenant_id")
    op.drop_index("ix_refund_lines_tenant_id", table_name="refund_lines")
    op.drop_constraint("fk_refund_lines_tenant_id_auth_tenants", "refund_lines", type_="foreignkey")
    op.drop_column("refund_lines", "tenant_id")
    op.drop_index("ix_refunds_tenant_id", table_name="refunds")
    op.drop_constraint("fk_refunds_tenant_id_auth_tenants", "refunds", type_="foreignkey")
    op.drop_column("refunds", "tenant_id")
    op.drop_index("ix_reviews_tenant_id", table_name="reviews")
    op.drop_constraint("fk_reviews_tenant_id_auth_tenants", "reviews", type_="foreignkey")
    op.drop_column("reviews", "tenant_id")
    op.drop_index("ix_shipping_rates_tenant_id", table_name="shipping_rates")
    op.drop_constraint("fk_shipping_rates_tenant_id_auth_tenants", "shipping_rates", type_="foreignkey")
    op.drop_column("shipping_rates", "tenant_id")
    op.drop_index("ix_shipping_zones_tenant_id", table_name="shipping_zones")
    op.drop_constraint("fk_shipping_zones_tenant_id_auth_tenants", "shipping_zones", type_="foreignkey")
    op.drop_column("shipping_zones", "tenant_id")
    op.drop_index("ix_stores_tenant_id", table_name="stores")
    op.drop_constraint("fk_stores_tenant_id_auth_tenants", "stores", type_="foreignkey")
    op.drop_column("stores", "tenant_id")
    op.drop_index("ix_tags_tenant_id", table_name="tags")
    op.drop_constraint("fk_tags_tenant_id_auth_tenants", "tags", type_="foreignkey")
    op.drop_column("tags", "tenant_id")
    op.drop_index("ix_tax_rates_tenant_id", table_name="tax_rates")
    op.drop_constraint("fk_tax_rates_tenant_id_auth_tenants", "tax_rates", type_="foreignkey")
    op.drop_column("tax_rates", "tenant_id")
    op.drop_index("ix_transactions_tenant_id", table_name="transactions")
    op.drop_constraint("fk_transactions_tenant_id_auth_tenants", "transactions", type_="foreignkey")
    op.drop_column("transactions", "tenant_id")
    op.drop_index("ix_variants_tenant_id", table_name="variants")
    op.drop_constraint("fk_variants_tenant_id_auth_tenants", "variants", type_="foreignkey")
    op.drop_column("variants", "tenant_id")
    op.drop_index("ix_webhooks_tenant_id", table_name="webhooks")
    op.drop_constraint("fk_webhooks_tenant_id_auth_tenants", "webhooks", type_="foreignkey")
    op.drop_column("webhooks", "tenant_id")
    op.drop_table("auth_provider_lock")
    op.drop_table("auth_invitations")
    op.drop_table("auth_verification_codes")
    op.drop_table("auth_users")
    op.drop_table("auth_tenants")
