"""A Shopify-style commerce backend, described as data for the Backend Builder.

Every entity here is created through the builder's public API by build_commerce.py. The model is
deliberately ambitious: it is meant to find the platform's limits, which are written down in
LIMITATIONS.md. Nothing in this file is generated code; it only describes the model.

Conventions
  * each store (merchant) is a tenant: signing up creates a store and its first admin
  * every entity is tenant-scoped (a `tenant` row rule on one operation puts the whole entity inside the
    tenant); other operations may add `owner` / `role_scoped` rules on top
  * money is `decimal` (the generator fixes it at NUMERIC(18, 6)); rates and percentages too
  * relations: one_to_many(from=Parent, to=Child, from_name="children", to_name="parent") puts the
    foreign key `<to_name>_id` on the child
"""

from typing import Any

Field = dict[str, Any]


def f(name: str, type_: str, *, req: bool = False, **extra: Any) -> Field:
    return {
        "name": name,
        "type": type_,
        "required": req,
        "unique": extra.pop("unique", False),
        "indexed": extra.pop("indexed", False),
        "default": extra.pop("default", None),
        "max_length": extra.pop("max_length", None),
        "min_value": extra.pop("min_value", None),
        "max_value": extra.pop("max_value", None),
        "enum_values": extra.pop("enum_values", None),
    }


def money(name: str, *, req: bool = False, default: float | None = 0) -> Field:
    return f(name, "decimal", req=req, min_value=0, default=default)


def text(name: str, length: int = 255, *, req: bool = False, **extra: Any) -> Field:
    return f(name, "string", req=req, max_length=length, **extra)


CURRENCIES = ["USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY"]
ADDRESS = [
    text("name", 120),
    text("company", 120),
    text("address1", 200, req=True),
    text("address2", 200),
    text("city", 100, req=True),
    text("province", 100),
    text("province_code", 10),
    text("country", 100, req=True),
    text("country_code", 2, req=True),
    text("postal_code", 20),
    text("phone", 30),
]

# name -> options and fields -------------------------------------------------------------------
ENTITIES: dict[str, dict[str, Any]] = {
    "Store": {
        "fields": [
            text("name", 120, req=True),
            text("legal_name", 200),
            text("email", 254, req=True),
            text("domain", 253, indexed=True),
            text("currency", 3, req=True, default="USD"),
            text("timezone", 64, default="UTC"),
            f("weight_unit", "enum", enum_values=["kg", "g", "lb", "oz"], default="kg"),
            f(
                "plan",
                "enum",
                enum_values=["trial", "basic", "grow", "advanced", "plus"],
                default="trial",
            ),
            f("password_protected", "boolean", default=False),
            f("settings", "json"),
        ],
        "ops": ["list", "get", "create", "update"],
    },
    "Location": {
        "fields": [
            text("name", 120, req=True),
            f("active", "boolean", default=True),
            f("fulfills_online_orders", "boolean", default=True),
            *ADDRESS[2:],
        ],
        "filterable": ["active"],
        "searchable": ["name"],
    },
    "Tag": {
        "fields": [text("name", 60, req=True, indexed=True)],
        "searchable": ["name"],
    },
    "Collection": {
        "fields": [
            text("title", 200, req=True),
            text("handle", 200, req=True, indexed=True),
            f("description_html", "text"),
            f("kind", "enum", enum_values=["manual", "smart"], default="manual"),
            f("rules", "json"),
            f(
                "sort_order",
                "enum",
                enum_values=[
                    "manual",
                    "best_selling",
                    "title_asc",
                    "title_desc",
                    "price_asc",
                    "price_desc",
                    "newest",
                ],
                default="manual",
            ),
            f("published", "boolean", default=False),
            f("published_at", "datetime"),
            text("seo_title", 70),
            text("seo_description", 320),
        ],
        "filterable": ["kind", "published", "handle"],
        "sortable": ["title", "created_at"],
        "searchable": ["title", "handle"],
        "soft_delete": True,
    },
    "Product": {
        "fields": [
            text("title", 255, req=True),
            text("handle", 255, req=True, indexed=True),
            f("description_html", "text"),
            text("vendor", 120, indexed=True),
            text("product_type", 120, indexed=True),
            f(
                "status",
                "enum",
                req=True,
                enum_values=["draft", "active", "archived"],
                default="draft",
            ),
            f("tags_cache", "json"),
            f("options", "json"),
            f("published_at", "datetime"),
            text("seo_title", 70),
            text("seo_description", 320),
            f("requires_shipping", "boolean", default=True),
            f("taxable", "boolean", default=True),
        ],
        "filterable": ["status", "vendor", "product_type", "handle"],
        "sortable": ["title", "created_at", "updated_at", "published_at"],
        "searchable": ["title", "vendor", "handle"],
        "soft_delete": True,
    },
    "Variant": {
        "fields": [
            text("title", 255, req=True, default="Default"),
            text("sku", 100, unique=True),
            text("barcode", 64, indexed=True),
            money("price", req=True),
            money("compare_at_price", default=None),
            money("cost", default=None),
            f("weight", "float", min_value=0),
            f("position", "integer", default=1, min_value=1),
            text("option1", 255),
            text("option2", 255),
            text("option3", 255),
            f("taxable", "boolean", default=True),
            f("requires_shipping", "boolean", default=True),
            f("inventory_policy", "enum", enum_values=["deny", "continue"], default="deny"),
            f("inventory_tracked", "boolean", default=True),
        ],
        "filterable": ["sku", "barcode"],
        "sortable": ["position", "price", "created_at"],
        "searchable": ["title", "sku", "barcode"],
    },
    "ProductImage": {
        "fields": [
            text("url", 2000, req=True),
            text("alt", 512),
            f("position", "integer", default=1, min_value=1),
            f("width", "integer", min_value=1),
            f("height", "integer", min_value=1),
        ],
        "sortable": ["position"],
    },
    "InventoryLevel": {
        "fields": [
            f("available", "integer", req=True, default=0),
            f("on_hand", "integer", default=0),
            f("committed", "integer", default=0, min_value=0),
            f("incoming", "integer", default=0, min_value=0),
        ],
        "filterable": ["available"],
        "sortable": ["available", "updated_at"],
    },
    "Customer": {
        "fields": [
            text("email", 254, indexed=True),
            text("first_name", 100),
            text("last_name", 100),
            text("phone", 30),
            f(
                "state",
                "enum",
                enum_values=["enabled", "disabled", "invited", "declined"],
                default="enabled",
            ),
            f("accepts_marketing", "boolean", default=False),
            f("accepts_marketing_updated_at", "datetime"),
            f("tax_exempt", "boolean", default=False),
            money("total_spent"),
            f("orders_count", "integer", default=0, min_value=0),
            f("tags_cache", "json"),
            f("note", "text"),
            text("locale", 10),
        ],
        "filterable": ["state", "accepts_marketing", "email"],
        "sortable": ["created_at", "total_spent", "orders_count"],
        "searchable": ["email", "first_name", "last_name", "phone"],
        "soft_delete": True,
    },
    "CustomerAddress": {
        "fields": [*ADDRESS, f("is_default", "boolean", default=False)],
    },
    "Cart": {
        "fields": [
            text("token", 64, req=True, unique=True),
            text("email", 254),
            text("currency", 3, req=True, default="USD"),
            f("status", "enum", enum_values=["open", "abandoned", "converted"], default="open"),
            text("discount_code", 64),
            f("note", "text"),
            f("attributes", "json"),
            f("expires_at", "datetime"),
        ],
        "filterable": ["status", "token"],
        "sortable": ["created_at", "updated_at"],
    },
    "CartLine": {
        "fields": [
            f("quantity", "integer", req=True, default=1, min_value=1, max_value=10000),
            f("properties", "json"),
        ],
    },
    "ShippingZone": {
        "fields": [text("name", 120, req=True), f("countries", "json", req=True)],
    },
    "ShippingRate": {
        "fields": [
            text("name", 120, req=True),
            money("price", req=True),
            money("min_order_subtotal", default=None),
            f("min_weight", "float", min_value=0),
            f("max_weight", "float", min_value=0),
            f("active", "boolean", default=True),
        ],
    },
    "TaxRate": {
        "fields": [
            text("country_code", 2, req=True, indexed=True),
            text("province_code", 10),
            text("name", 100, req=True),
            f("rate", "decimal", req=True, min_value=0, max_value=1),
            f("includes_shipping", "boolean", default=False),
        ],
    },
    "Order": {
        "fields": [
            f("number", "bigint", req=True, unique=True, min_value=1),
            text("email", 254, indexed=True),
            f(
                "status",
                "enum",
                req=True,
                enum_values=["open", "closed", "cancelled"],
                default="open",
            ),
            f(
                "financial_status",
                "enum",
                enum_values=[
                    "pending",
                    "authorized",
                    "partially_paid",
                    "paid",
                    "partially_refunded",
                    "refunded",
                    "voided",
                ],
                default="pending",
            ),
            f(
                "fulfillment_status",
                "enum",
                enum_values=["unfulfilled", "partial", "fulfilled", "restocked"],
                default="unfulfilled",
            ),
            text("currency", 3, req=True, default="USD"),
            money("subtotal", req=True),
            money("shipping_total"),
            money("tax_total"),
            money("discount_total"),
            money("total", req=True),
            money("total_refunded"),
            f("billing_address", "json"),
            f("shipping_address", "json"),
            text("shipping_method", 120),
            text("discount_code", 64),
            f("note", "text"),
            f("tags_cache", "json"),
            text("source", 60, default="web"),
            f("placed_at", "datetime", req=True),
            f("closed_at", "datetime"),
            f("cancelled_at", "datetime"),
            f(
                "cancel_reason",
                "enum",
                enum_values=["customer", "fraud", "inventory", "declined", "other"],
            ),
        ],
        "ops": ["list", "get", "head", "create", "update"],
        "filterable": [
            "status",
            "financial_status",
            "fulfillment_status",
            "email",
            "number",
            "source",
        ],
        "sortable": ["placed_at", "total", "number", "created_at"],
        "searchable": ["email", "note"],
    },
    "OrderLine": {
        "fields": [
            text("title", 255, req=True),
            text("variant_title", 255),
            text("sku", 100),
            f("quantity", "integer", req=True, min_value=1),
            money("unit_price", req=True),
            money("discount_total"),
            money("tax_total"),
            f("fulfilled_quantity", "integer", default=0, min_value=0),
            f("refunded_quantity", "integer", default=0, min_value=0),
            f("properties", "json"),
        ],
        "ops": ["list", "get", "create", "update"],
    },
    "Transaction": {
        "fields": [
            f(
                "kind",
                "enum",
                req=True,
                enum_values=["authorization", "capture", "sale", "void", "refund"],
            ),
            f("status", "enum", req=True, enum_values=["pending", "success", "failure", "error"]),
            money("amount", req=True),
            text("currency", 3, req=True),
            text("gateway", 60),
            text("reference", 120, indexed=True),
            text("error_code", 60),
            f("processed_at", "datetime"),
        ],
        "ops": ["list", "get", "create"],
    },
    "Refund": {
        "fields": [
            money("amount", req=True),
            text("reason", 255),
            f("restock", "boolean", default=False),
            f("note", "text"),
        ],
        "ops": ["list", "get", "create"],
    },
    "RefundLine": {
        "fields": [f("quantity", "integer", req=True, min_value=1), money("subtotal", req=True)],
        "ops": ["list", "get", "create"],
    },
    "Fulfillment": {
        "fields": [
            f(
                "status",
                "enum",
                req=True,
                enum_values=["pending", "open", "success", "cancelled", "error"],
                default="pending",
            ),
            text("tracking_company", 120),
            text("tracking_number", 120, indexed=True),
            text("tracking_url", 2000),
            f("notify_customer", "boolean", default=True),
            f("shipped_at", "datetime"),
        ],
    },
    "FulfillmentLine": {
        "fields": [f("quantity", "integer", req=True, min_value=1)],
    },
    "OrderEvent": {
        "fields": [
            f(
                "verb",
                "enum",
                req=True,
                enum_values=[
                    "placed",
                    "paid",
                    "fulfilled",
                    "refunded",
                    "cancelled",
                    "note",
                    "email_sent",
                    "edited",
                ],
            ),
            f("message", "text"),
            text("actor", 254),
            f("data", "json"),
        ],
        "ops": ["list", "get", "create"],
        "sortable": ["created_at"],
    },
    "Discount": {
        "fields": [
            text("code", 64, req=True, unique=True),
            text("title", 120),
            f(
                "kind",
                "enum",
                req=True,
                enum_values=["percentage", "fixed_amount", "free_shipping", "buy_x_get_y"],
            ),
            f("value", "decimal", req=True, min_value=0),
            f("target", "enum", enum_values=["order", "line_item", "shipping"], default="order"),
            money("minimum_subtotal", default=None),
            f("usage_limit", "integer", min_value=1),
            f("once_per_customer", "boolean", default=False),
            f("used_count", "integer", default=0, min_value=0),
            f("combines_with_other", "boolean", default=False),
            f("applies_to", "json"),
            f("starts_at", "datetime"),
            f("ends_at", "datetime"),
            f("active", "boolean", default=True),
        ],
        "filterable": ["kind", "active", "code"],
        "searchable": ["code", "title"],
    },
    "DiscountUsage": {
        "fields": [money("amount", req=True), text("email", 254)],
        "ops": ["list", "get", "create"],
    },
    "GiftCard": {
        "fields": [
            text("code", 32, req=True, unique=True),
            money("initial_value", req=True),
            money("balance", req=True),
            text("currency", 3, req=True),
            f("expires_on", "date"),
            f("disabled", "boolean", default=False),
            f("note", "text"),
        ],
        "filterable": ["disabled", "code"],
    },
    "Review": {
        "fields": [
            f("rating", "integer", req=True, min_value=1, max_value=5),
            text("title", 200),
            f("body", "text"),
            text("author_name", 120),
            f(
                "status",
                "enum",
                enum_values=["pending", "published", "rejected"],
                default="pending",
            ),
            f("verified_purchase", "boolean", default=False),
        ],
        "ops": ["list", "get", "create", "update", "delete"],
        "filterable": ["status", "rating"],
        "sortable": ["created_at", "rating"],
        "searchable": ["title", "body"],
    },
    "Webhook": {
        "fields": [
            f(
                "topic",
                "enum",
                req=True,
                enum_values=[
                    "orders.create",
                    "orders.paid",
                    "orders.cancelled",
                    "products.create",
                    "products.update",
                    "customers.create",
                    "refunds.create",
                    "fulfillments.create",
                ],
            ),
            text("url", 2000, req=True),
            f("body_format", "enum", enum_values=["json", "xml"], default="json"),
            text("secret", 128),
            f("active", "boolean", default=True),
        ],
    },
    "Metafield": {
        "fields": [
            text("owner_type", 40, req=True, indexed=True),
            f("owner_id", "uuid", req=True, indexed=True),
            text("namespace", 60, req=True),
            text("key", 60, req=True),
            f(
                "value_type",
                "enum",
                req=True,
                enum_values=["string", "integer", "decimal", "boolean", "json", "date"],
            ),
            f("value", "json", req=True),
        ],
        "filterable": ["owner_type", "owner_id", "namespace", "key"],
    },
    "Blog": {
        "fields": [
            text("title", 200, req=True),
            text("handle", 200, req=True, indexed=True),
            f("commentable", "boolean", default=False),
        ],
    },
    "Article": {
        "fields": [
            text("title", 255, req=True),
            text("handle", 255, req=True, indexed=True),
            text("author", 120),
            f("body_html", "text"),
            f("summary_html", "text"),
            f("published", "boolean", default=False),
            f("published_at", "datetime"),
            f("tags_cache", "json"),
        ],
        "filterable": ["published", "handle"],
        "sortable": ["published_at", "created_at"],
        "searchable": ["title", "author"],
        "soft_delete": True,
    },
    "Page": {
        "fields": [
            text("title", 255, req=True),
            text("handle", 255, req=True, indexed=True),
            f("body_html", "text"),
            f("published", "boolean", default=False),
            text("template_suffix", 60),
        ],
        "filterable": ["published", "handle"],
    },
}

# (kind, from, to, from_name, to_name, on_delete, required)
RELATIONS: list[tuple[str, str, str, str, str, str, bool]] = [
    ("one_to_many", "Product", "Variant", "variants", "product", "cascade", True),
    ("one_to_many", "Product", "ProductImage", "images", "product", "cascade", True),
    ("one_to_many", "Product", "Review", "reviews", "product", "cascade", True),
    ("many_to_many", "Collection", "Product", "products", "collections", "cascade", False),
    ("many_to_many", "Product", "Tag", "tags", "products", "cascade", False),
    ("one_to_many", "Collection", "Collection", "children", "parent", "set_null", False),
    ("one_to_many", "Variant", "InventoryLevel", "inventory_levels", "variant", "cascade", True),
    ("one_to_many", "Location", "InventoryLevel", "inventory_levels", "location", "restrict", True),
    ("one_to_many", "Customer", "CustomerAddress", "addresses", "customer", "cascade", True),
    ("one_to_many", "Customer", "Order", "orders", "customer", "set_null", False),
    ("one_to_many", "Customer", "Cart", "carts", "customer", "set_null", False),
    ("one_to_many", "Customer", "Review", "reviews", "customer", "set_null", False),
    ("one_to_many", "Customer", "GiftCard", "gift_cards", "customer", "set_null", False),
    ("one_to_many", "Cart", "CartLine", "lines", "cart", "cascade", True),
    ("one_to_many", "Variant", "CartLine", "cart_lines", "variant", "restrict", True),
    ("one_to_one", "Cart", "Order", "order", "cart", "set_null", False),
    ("one_to_many", "Order", "OrderLine", "lines", "order", "cascade", True),
    ("one_to_many", "Variant", "OrderLine", "order_lines", "variant", "set_null", False),
    ("one_to_many", "Order", "Transaction", "transactions", "order", "restrict", True),
    ("one_to_many", "Order", "Refund", "refunds", "order", "restrict", True),
    ("one_to_many", "Refund", "RefundLine", "lines", "refund", "cascade", True),
    ("one_to_many", "OrderLine", "RefundLine", "refund_lines", "order_line", "restrict", True),
    ("one_to_many", "Order", "Fulfillment", "fulfillments", "order", "restrict", True),
    ("one_to_many", "Location", "Fulfillment", "fulfillments", "location", "set_null", False),
    ("one_to_many", "Fulfillment", "FulfillmentLine", "lines", "fulfillment", "cascade", True),
    (
        "one_to_many",
        "OrderLine",
        "FulfillmentLine",
        "fulfillment_lines",
        "order_line",
        "restrict",
        True,
    ),
    ("one_to_many", "Order", "OrderEvent", "events", "order", "cascade", True),
    ("one_to_many", "Discount", "DiscountUsage", "usages", "discount", "cascade", True),
    ("one_to_many", "Order", "DiscountUsage", "discount_usages", "order", "cascade", True),
    ("one_to_many", "ShippingZone", "ShippingRate", "rates", "zone", "cascade", True),
    ("one_to_many", "ShippingRate", "Order", "orders", "shipping_rate", "set_null", False),
    ("one_to_many", "Blog", "Article", "articles", "blog", "cascade", True),
]

# Roles. The founder of a store becomes `admin`; staff arrive by invitation; every account also
# gets the default role.
ROLES: list[dict[str, Any]] = [
    {"name": "manager", "label": "Store manager", "invite_only": True},
    {"name": "catalog", "label": "Catalog editor", "invite_only": True},
    {"name": "fulfillment", "label": "Fulfillment", "invite_only": True},
    {"name": "support", "label": "Customer support", "invite_only": True},
    {"name": "marketing", "label": "Marketing", "invite_only": True},
    # A role can only inherit from one that already exists, so the parent comes first.
    {"name": "admin", "label": "Store owner", "inherits_from": "manager", "invite_only": True},
    {"name": "customer", "label": "Customer", "is_default": True},
]

CUSTOM_FIELDS = [
    {
        "name": "display_name",
        "label": "Display name",
        "type": "string",
        "required": True,
        "max_length": 80,
    },
    {
        "name": "locale",
        "label": "Language",
        "type": "enum",
        "enum_values": ["en", "fr", "de", "hi", "ja"],
        "default_value": "en",
    },
    {
        "name": "marketing_opt_in",
        "label": "Marketing emails",
        "type": "boolean",
        "default_value": "false",
    },
    {"name": "job_title", "label": "Job title", "type": "string", "max_length": 80},
]

ALL_STAFF = ["manager", "catalog", "fulfillment", "support", "marketing"]
CATALOG = ["manager", "catalog"]
ORDERS = ["manager", "fulfillment", "support"]
SALES = ["manager", "fulfillment", "support", "marketing"]
ANY = [*ALL_STAFF, "customer"]
ALL_OPS = ["list", "get", "head", "create", "replace", "update", "delete"]

# entity -> {operation: (roles, row rule or None)}. `tenant` rule on one operation puts the whole
# entity inside the tenant; here it is on every operation that has a permission.
READ = ["list", "get", "head"]


def _rule(
    entity: str, ops: list[str], roles: list[str], rule: str = "tenant"
) -> list[tuple[str, str, list[str], dict[str, Any]]]:
    return [(entity, op, roles, {"row_rule": rule}) for op in ops]


def permissions() -> list[tuple[str, str, list[str], dict[str, Any]]]:
    p: list[tuple[str, str, list[str], dict[str, Any]]] = []
    # settings and configuration: managers
    p += _rule("Store", READ, ANY[:-1]) + _rule("Store", ["create", "update"], ["manager"])
    for e in ("Location", "ShippingZone", "ShippingRate", "TaxRate", "Webhook"):
        p += _rule(e, READ, ALL_STAFF) + _rule(
            e, ["create", "replace", "update", "delete"], ["manager"]
        )
    # catalog: everyone reads, catalog editors write
    for e in (
        "Product",
        "Variant",
        "ProductImage",
        "Collection",
        "Tag",
        "Blog",
        "Article",
        "Page",
        "Metafield",
    ):
        p += _rule(e, READ, ANY) + _rule(e, ["create", "replace", "update"], CATALOG)
        p += _rule(e, ["delete"], ["manager"])
    p += _rule("InventoryLevel", READ, ALL_STAFF) + _rule(
        "InventoryLevel", ["create", "replace", "update"], ["manager", "catalog", "fulfillment"]
    )
    p += _rule("InventoryLevel", ["delete"], ["manager"])
    # customers
    for e in ("Customer", "CustomerAddress"):
        p += _rule(e, READ, ["manager", "support", "marketing"]) + _rule(
            e, ["create", "replace", "update"], ["manager", "support"]
        )
        p += _rule(e, ["delete"], ["manager"])
    # carts: customers can create one; reading and changing them is staff-only. A row rule applies to
    # every role of a slot, so "customers see only their own cart" and "staff see all carts" cannot
    # both be expressed on the same operation (see LIMITATIONS.md).
    for e in ("Cart", "CartLine"):
        p += _rule(e, ["create"], ANY)
        p += _rule(e, READ, ["manager", "support", "marketing"])
        p += _rule(e, ["replace", "update", "delete"], ["manager", "support"])
    # orders: customers can place one; running them is staff-only, for the same reason as carts
    p += _rule("Order", ["create"], ANY) + _rule("Order", READ, ORDERS + ["marketing"])
    p += _rule("Order", ["update"], ORDERS)
    for e in ("OrderLine", "OrderEvent"):
        p += _rule(e, ["create"], ANY if e == "OrderLine" else ORDERS)
        p += _rule(e, ["list", "get"], ORDERS + ["marketing"])
    p += _rule("OrderLine", ["update"], ORDERS)
    for e in ("Transaction", "Refund", "RefundLine"):
        p += _rule(e, READ, ORDERS) + _rule(
            e, ["create"], ["manager", "support"] if e != "Transaction" else ORDERS
        )
    for e in ("Fulfillment", "FulfillmentLine"):
        p += _rule(e, READ, ORDERS) + _rule(
            e, ["create", "replace", "update"], ["manager", "fulfillment"]
        )
        p += _rule(e, ["delete"], ["manager"])
    # promotions
    for e in ("Discount", "DiscountUsage", "GiftCard"):
        ops = ["create"] if e == "DiscountUsage" else ["create", "replace", "update"]
        p += _rule(e, READ, SALES) + _rule(e, ops, ["manager", "marketing"])
        if e != "DiscountUsage":
            p += _rule(e, ["delete"], ["manager"])
    # reviews: customers write their own, marketing moderates
    p += _rule("Review", ["list", "get"], ANY) + _rule("Review", ["create"], ANY)
    p += _rule("Review", ["update", "delete"], ["manager", "marketing"])
    return p
