"""Try to break the commerce backend, and report what the platform can and cannot do.

    python examples/commerce/populate_commerce.py     # first: seeded data and users
    python examples/commerce/probe_limits.py          # then: run the probes

Each probe prints a verdict:
  OK     the platform handles it the way a commerce backend needs
  RISK   it works, but it is a security or data-integrity hazard you must know about
  LIMIT  the platform cannot express it; the application (frontend or a service) has to supply it

The probes only use the public API and the seeded users. They create throw-away rows (prefixed
"probe") and clean up what they can. The findings are written up in LIMITATIONS.md.
"""

import concurrent.futures
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from populate_commerce import PASSWORD, Http, Mail  # noqa: E402

HERE = Path(__file__).resolve().parent
results: list[tuple[str, str, str, str]] = []


def verdict(kind: str, key: str, title: str, evidence: str) -> None:
    results.append((kind, key, title, evidence))
    print(f"{kind:5} {key:24} {title}\n        {evidence}")


def short(body: Any) -> str:
    text = json.dumps(body) if not isinstance(body, str) else body
    return text[:160]


def main() -> int:
    seeded = json.loads((HERE / "seeded.json").read_text(encoding="utf-8"))
    api = Http(seeded["api"])

    def login(email: str) -> str:
        return str(
            api.ok("POST", "/auth/login", {"email": email, "password": PASSWORD})["access_token"]
        )

    # Read-only probes use the seeded stores. Everything that writes runs from a throw-away "lab"
    # store created here, so the seeded data is never touched.
    mail = Mail(seeded.get("mail", "http://localhost:8025"))
    lab_email = f"lab.{uuid.uuid4().hex[:8]}@lab.test"
    api.ok(
        "POST",
        "/auth/register",
        {
            "email": lab_email,
            "password": PASSWORD,
            "display_name": "Lab Owner",
            "tenant_name": "Probe Lab",
        },
        expect=201,
    )
    api.ok("POST", "/auth/email/verify", {"token": mail.token_for(lab_email)})
    lab = login(
        lab_email
    )  # the founder: admin, which inherits manager (catalog, orders, settings...)

    acme_admin, acme_mgr, acme_cat = (
        login("ava@acme.test"),
        login("mia.manager@acme.test"),
        login("carl.catalog@acme.test"),
    )
    acme_sup = login("sam.support@acme.test")
    acme_cust = login("zara@acme-shopper.test")
    glx_cat = login("carl.catalog@globex.test")

    def first(path: str, token: str) -> dict[str, Any]:
        items = api.ok("GET", f"{path}?limit=1", token=token)["items"]
        return dict(items[0])

    # --- tenant isolation -------------------------------------------------------------------
    acme_total = api.ok("GET", "/products?limit=1", token=acme_cat)["total"]
    glx_total = api.ok("GET", "/products?limit=1", token=glx_cat)["total"]
    handles = {p["handle"] for p in api.ok("GET", "/products?limit=100", token=glx_cat)["items"]}
    verdict(
        "OK",
        "isolation.lists",
        "Each store only sees its own rows",
        f"acme sees {acme_total} products, globex {glx_total}, no overlap: {not any(h.startswith('acme-') for h in handles)}",
    )

    acme_product = first("/products", acme_cat)
    status, body = api.call("GET", f"/products/{acme_product['id']}", token=glx_cat)
    verdict(
        "OK" if status == 404 else "RISK",
        "isolation.get",
        "Reading another store's row by id",
        f"HTTP {status}",
    )

    # the foreign-key hole: a row may point at a parent that belongs to another tenant
    status, body = api.call(
        "POST",
        "/variants",
        {"product_id": acme_product["id"], "title": "probe injected", "price": "1.00"},
        lab,
    )
    leaked = status == 201
    verdict(
        "RISK" if leaked else "OK",
        "isolation.fk_create",
        "Create a child under ANOTHER store's parent (variant -> foreign product)",
        f"HTTP {status}: {short(body)}",
    )
    if leaked:
        inj = body["id"]
        status, seen = api.call("GET", f"/variants/{inj}", token=lab)
        verdict(
            "RISK",
            "isolation.fk_read",
            "The foreign parent id is now stored on this store's row",
            f"HTTP {status}; product_id={seen.get('product_id') if isinstance(seen, dict) else seen}",
        )
        api.call("DELETE", f"/variants/{inj}", token=lab)
    # the lab store's own rows, used by the destructive probes below
    lab_product = api.ok(
        "POST", "/products", {"title": "probe base", "handle": "probe-base"}, lab, expect=201
    )
    lab_variant = api.ok(
        "POST",
        "/variants",
        {
            "product_id": lab_product["id"],
            "title": "base",
            "sku": f"LAB-{uuid.uuid4().hex[:6]}",
            "price": "5",
        },
        lab,
        expect=201,
    )
    lab_order = api.ok(
        "POST",
        "/orders",
        {
            "number": uuid.uuid4().int % 10**9,
            "currency": "USD",
            "subtotal": "5",
            "total": "5",
            "placed_at": "2026-01-01T00:00:00Z",
        },
        lab,
        expect=201,
    )

    other_variant = first("/variants", acme_cat)
    status, body = api.call(
        "POST",
        "/order_lines",
        {
            "order_id": lab_order["id"],
            "variant_id": other_variant["id"],
            "title": "probe",
            "quantity": 1,
            "unit_price": "1",
        },
        lab,
    )
    verdict(
        "RISK" if status == 201 else "OK",
        "isolation.fk_order_line",
        "Order line pointing at another store's variant",
        f"HTTP {status}",
    )
    lab_collection = api.ok(
        "POST", "/collections", {"title": "probe", "handle": "probe-col"}, lab, expect=201
    )
    status, body = api.call(
        "PATCH", f"/collections/{lab_collection['id']}", {"products": [acme_product["id"]]}, lab
    )
    verdict(
        "RISK" if status == 200 else "OK",
        "isolation.m2m",
        "Many-to-many link to another store's product",
        f"HTTP {status}",
    )
    status, body = api.call(
        "PATCH", f"/variants/{lab_variant['id']}", {"product_id": acme_product["id"]}, lab
    )
    verdict(
        "RISK" if status == 200 else "OK",
        "isolation.fk_move",
        "Re-parent an existing row under another store's parent",
        f"HTTP {status}",
    )
    status, body = api.call(
        "POST",
        "/tags",
        {"name": "probe-forge", "tenant_id": str(uuid.uuid4()), "created_by_id": str(uuid.uuid4())},
        lab,
    )
    verdict(
        "OK",
        "isolation.forge",
        "tenant_id / created_by_id in a request body",
        f"HTTP {status}: extra fields {'rejected' if status == 422 else 'ignored' if status == 201 else '??'}",
    )

    # --- uniqueness is global, not per store -------------------------------------------------
    glx_sku = first("/variants", glx_cat)["sku"]
    status, body = api.call(
        "POST",
        "/variants",
        {"product_id": lab_product["id"], "title": "probe", "sku": glx_sku, "price": "1"},
        lab,
    )
    verdict(
        "RISK",
        "unique.sku_global",
        "SKU uniqueness spans ALL stores",
        f"a third store creating sku {glx_sku} (a globex SKU) -> HTTP {status}: it fails, and that also reveals another store uses it",
    )
    status, body = api.call(
        "POST", "/discounts", {"code": "GLOBEXWELCOME10", "kind": "percentage", "value": "5"}, lab
    )
    verdict(
        "LIMIT",
        "unique.discount_code",
        "Discount codes, order numbers, cart tokens are unique across all stores",
        f"a store reusing globex's code -> HTTP {status}. Stores cannot both have order #1001 or code WELCOME10; the seed prefixes everything with a store key",
    )
    status, body = api.call(
        "POST",
        "/variants",
        {"product_id": lab_product["id"], "title": "dup", "sku": lab_variant["sku"], "price": "1"},
        lab,
    )
    verdict(
        "OK",
        "unique.same_store",
        "Duplicate SKU inside one store is refused",
        f"HTTP {status}: {short(body)}",
    )

    # --- storefront / customers --------------------------------------------------------------
    status, body = api.call("GET", "/products", token=None)
    verdict(
        "LIMIT",
        "storefront.anonymous",
        "No public (logged-out) storefront read of tenant data",
        f"GET /products without a token -> HTTP {status}. A tenant is resolved from the signed-in user, never from a domain or header",
    )
    status, body = api.call(
        "POST",
        "/auth/register",
        {
            "email": f"shopper.{uuid.uuid4().hex[:6]}@example.com",
            "password": PASSWORD,
            "display_name": "Shopper",
        },
        None,
    )
    verdict(
        "LIMIT",
        "storefront.signup",
        "Customers cannot sign up to an existing store",
        f"register without an invitation -> HTTP {status} ({body.get('code') if isinstance(body, dict) else body}): a sign-up must either create a NEW store or carry an invitation. Only invitations add people to a store",
    )
    status, body = api.call("GET", "/orders", token=acme_cust)
    verdict("OK", "customer.orders_blocked", "A customer cannot read orders", f"HTTP {status}")
    status, body = api.call("GET", "/products", token=acme_cust)
    verdict(
        "OK",
        "customer.catalog_read",
        "A customer can read the catalog, drafts and archived included",
        f"HTTP {status}; statuses seen {sorted({p['status'] for p in body['items']})}"
        if status == 200
        else f"HTTP {status}",
    )
    verdict(
        "LIMIT",
        "customer.own_orders",
        "Customers cannot be shown ONLY their own orders while staff see all",
        "a row rule applies to every role listed on an operation: 'tenant' for staff would show a customer the whole store, 'owner' would hide orders from staff. Orders are staff-only in this model",
    )
    verdict(
        "LIMIT",
        "customer.draft_hidden",
        "Customers cannot be shown only active products",
        "no per-role filter: a custom_filter on status would hide drafts from the staff who need them too",
    )

    # --- roles and users ---------------------------------------------------------------------
    status, body = api.call(
        "POST",
        "/auth/invitations",
        {"email": f"probe.{uuid.uuid4().hex[:6]}@acme.test", "roles": ["manager"]},
        acme_mgr,
    )
    verdict(
        "OK",
        "roles.invite_admin_only",
        "Only the store admin can invite",
        f"manager inviting -> HTTP {status}",
    )
    for path in ("/auth/users", "/users", "/auth/members"):
        status, body = api.call("GET", path, token=lab)
    verdict(
        "LIMIT",
        "roles.no_user_admin",
        "No endpoints to list staff, change a role, deactivate or remove a user",
        f"GET /auth/users, /users, /auth/members -> HTTP {status}. After inviting someone the store admin cannot demote them or cut their access (only the person can delete their own account)",
    )
    status, body = api.call(
        "POST", "/auth/password-reset/request", {"email": "ava@acme.test"}, None
    )
    verdict(
        "LIMIT",
        "auth.no_password_reset",
        "Password reset exists only with email magic link or SMS enabled",
        f"HTTP {status} with magic links off; this model would need magic links on so people can reset passwords",
    )
    me = api.ok("GET", "/auth/me", token=acme_sup)
    verdict(
        "RISK",
        "roles.default_role",
        "Every account also holds the default role",
        f"the support user's roles are {me['roles']}: the default role is added to everyone, so it must stay harmless",
    )
    verdict(
        "LIMIT",
        "auth.one_store_per_email",
        "A person cannot belong to two stores with one login (by design, read from the generated model)",
        "emails are globally unique across tenants, so an agency worker needs one account per store",
    )

    # --- permissions defaults -----------------------------------------------------------------
    verdict(
        "RISK",
        "permissions.unlisted_public",
        "An operation with no permission is open to every signed-in user (documented behaviour)",
        "the builder does not warn; build_commerce.py audits for this and refuses to build if any enabled operation is unlisted. The first draft of this model had 6 such holes",
    )

    # --- data model and integrity -------------------------------------------------------------
    order = first("/orders", acme_sup)
    status, body = api.call(
        "POST",
        "/orders",
        {
            "number": uuid.uuid4().int % 10**9,
            "status": "open",
            "currency": "USD",
            "subtotal": "10",
            "total": "1",
            "placed_at": "2026-01-01T00:00:00Z",
        },
        lab,
    )
    verdict(
        "LIMIT",
        "integrity.totals",
        "No computed fields or cross-field rules: total is never checked against its parts",
        f"order with subtotal 10 and total 1 -> HTTP {status}",
    )
    if status == 201:
        oid = body["id"]
        api.ok("PATCH", f"/orders/{oid}", {"status": "cancelled"}, lab)
        status2, _ = api.call(
            "PATCH",
            f"/orders/{oid}",
            {
                "status": "open",
                "number": uuid.uuid4().int % 10**9,
                "placed_at": "1999-01-01T00:00:00Z",
            },
            lab,
        )
        verdict(
            "LIMIT",
            "integrity.state_machine",
            "No state machines or immutable fields",
            f"cancelled->open, changing the order number and placed_at -> HTTP {status2}. Rules like 'a paid order cannot be edited' need a service in front",
        )
    status, body = api.call(
        "POST",
        "/order_lines",
        {"order_id": lab_order["id"], "title": "probe", "quantity": 1000000, "unit_price": "1"},
        lab,
    )
    verdict(
        "LIMIT",
        "integrity.stock",
        "No stock check, no inventory decrement, no reservation",
        f"order line for 1,000,000 units -> HTTP {status}; stock changes are a separate PATCH the client must make (and can race)",
    )
    lab_loc = api.ok(
        "POST",
        "/locations",
        {
            "name": "probe loc",
            "address1": "1 Lab Street",
            "city": "Lab",
            "country": "Land",
            "country_code": "LL",
        },
        lab,
        expect=201,
    )
    level = api.ok(
        "POST",
        "/inventory_levels",
        {"variant_id": lab_variant["id"], "location_id": lab_loc["id"], "available": 1},
        lab,
        expect=201,
    )

    def decrement(_: int) -> int:
        current = api.ok("GET", f"/inventory_levels/{level['id']}", token=lab)["available"]
        return (
            int(
                api.call(
                    "PATCH", f"/inventory_levels/{level['id']}", {"available": current - 1}, lab
                )[0]
                == 200
            )
            * current
        )

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        saw = list(pool.map(decrement, range(8)))
    final = api.ok("GET", f"/inventory_levels/{level['id']}", token=lab)["available"]
    verdict(
        "LIMIT",
        "integrity.no_atomic_update",
        "No atomic increment/decrement and no optimistic locking",
        f"8 parallel 'take 1' read-modify-writes from stock 1 left available={final} (a correct system ends at 1-8=-7 or refuses): every worker saw stock {sorted(set(saw))}. A checkout needs UPDATE ... SET available = available - n",
    )
    status, body = api.call("PATCH", f"/inventory_levels/{level['id']}", {"available": -50}, lab)
    verdict(
        "LIMIT",
        "integrity.negative_stock",
        "No CHECK constraints beyond min/max on a field",
        f"available = -50 -> HTTP {status}: the field has no minimum, so overselling is representable (declare min_value to prevent it)",
    )
    status, body = api.call(
        "POST",
        "/variants",
        {"product_id": lab_product["id"], "title": "probe money", "price": "19.99999999"},
        lab,
    )
    verdict(
        "LIMIT",
        "money.precision",
        "Money is a fixed NUMERIC(18,6) with no currency, rounding or per-field scale",
        f"price 19.99999999 -> HTTP {status}: stored as {body.get('price') if isinstance(body, dict) else body}",
    )
    status, body = api.call(
        "POST",
        "/variants",
        {"product_id": lab_product["id"], "title": "probe huge", "price": "99999999999999"},
        lab,
    )
    verdict(
        "RISK" if status >= 500 else "OK",
        "money.overflow",
        "A number too large for the column",
        f"price 99999999999999 -> HTTP {status}: {short(body)} (a client error becomes a server error: BUG)",
    )
    status, body = api.call(
        "POST",
        "/products",
        {
            "title": "probe xss",
            "handle": "probe-xss",
            "description_html": "<script>alert(1)</script>",
        },
        lab,
    )
    verdict(
        "LIMIT",
        "content.no_sanitising",
        "HTML fields are stored and returned verbatim",
        f"<script> accepted -> HTTP {status}; the storefront must sanitise",
    )
    api.ok(
        "POST",
        "/webhooks",
        {
            "topic": "orders.create",
            "url": "https://hooks.example.com/probe",
            "secret": "whsec_probe_secret",
        },
        lab,
        expect=201,
    )
    status, body = api.call("GET", "/webhooks", token=lab)
    secret = body["items"][0].get("secret") if status == 200 and body["items"] else None
    verdict(
        "RISK" if secret else "OK",
        "content.secrets_readable",
        "Secrets stored in an entity are returned by reads",
        f"webhook secret in GET /webhooks: {secret!r} (no write-only fields; any role allowed to read webhooks sees it)",
    )

    # --- soft delete ---------------------------------------------------------------------------
    product = api.ok(
        "POST", "/products", {"title": "probe soft", "handle": "probe-soft"}, lab, expect=201
    )
    variant = api.ok(
        "POST",
        "/variants",
        {
            "product_id": product["id"],
            "title": "child",
            "sku": f"PROBE-SOFT-{uuid.uuid4().hex[:6]}",
            "price": "1",
        },
        lab,
        expect=201,
    )
    api.ok("DELETE", f"/products/{product['id']}", token=lab, expect=204)
    status, body = api.call("GET", f"/variants/{variant['id']}", token=lab)
    verdict(
        "LIMIT",
        "softdelete.cascade",
        "Soft deleting a parent does not hide or delete its children",
        f"product soft-deleted; its variant is still returned (HTTP {status})",
    )
    status, body = api.call(
        "POST",
        "/variants",
        {"product_id": lab_product["id"], "title": "again", "sku": variant["sku"], "price": "1"},
        lab,
    )
    verdict(
        "LIMIT",
        "softdelete.unique",
        "A soft-deleted row still holds its unique values",
        f"a deleted product's variant keeps its SKU reserved; re-using it -> HTTP {status}",
    )
    status, body = api.call("DELETE", f"/orders/{order['id']}", token=acme_admin)
    verdict(
        "OK", "delete.orders", "Orders cannot be deleted (operation not enabled)", f"HTTP {status}"
    )
    cust = first("/customers", acme_sup)
    status, body = api.call(
        "DELETE", f"/products/{first('/products', acme_cat)['id']}", token=acme_cat
    )
    verdict("OK", "delete.role", "A catalog editor cannot delete products", f"HTTP {status}")
    api.ok(
        "POST",
        "/inventory_levels",
        {"variant_id": lab_variant["id"], "location_id": lab_loc["id"], "available": 1},
        lab,
        expect=201,
    )
    verdict(
        "LIMIT",
        "model.composite_unique",
        "Composite unique/indexes",
        "a second inventory level for the same (variant, location) was just accepted; 'one per pair' cannot be declared",
    )
    status, body = api.call("DELETE", f"/locations/{lab_loc['id']}", token=lab)
    verdict(
        "OK",
        "delete.restrict",
        "Deleting a location that stock points to is refused",
        f"HTTP {status}: {short(body)}",
    )

    # --- querying ------------------------------------------------------------------------------
    status, body = api.call("GET", f"/orders?customer_id={cust['id']}", token=acme_sup)
    verdict(
        "LIMIT",
        "query.fk_filter",
        "Cannot filter by a relation (orders of one customer)",
        f"?customer_id=... -> HTTP {status}; total {body.get('total') if isinstance(body, dict) else body}: the filter is {'ignored' if status == 200 else 'rejected'}. Only declared exact-match fields filter",
    )
    status, body = api.call("GET", "/orders?total__gte=100", token=acme_sup)
    verdict(
        "LIMIT",
        "query.ranges",
        "No range, 'in', or date filters (price between, orders since a date)",
        f"?total__gte=100 -> HTTP {status}: {'ignored' if status == 200 else 'rejected'}",
    )
    status, body = api.call("GET", "/orders?sort=-placed_at,total", token=acme_sup)
    verdict(
        "LIMIT",
        "query.multi_sort",
        "One sort field at a time",
        f"?sort=-placed_at,total -> HTTP {status}",
    )
    status, body = api.call("GET", "/products?limit=1000", token=acme_cat)
    verdict(
        "OK", "query.page_cap", "Page size is capped", f"limit=1000 -> HTTP {status}: {short(body)}"
    )
    detail = api.ok("GET", f"/orders/{order['id']}", token=acme_sup)
    verdict(
        "LIMIT",
        "query.no_expand",
        "A parent returns child ids, not child rows; no aggregates or reports",
        f"order has {len(detail.get('lines', []))} line ids and {len(detail.get('transactions', []))} transaction ids: rendering one order page takes 1 + N requests. There is no sum/count/group-by (sales per day, top products)",
    )
    status, body = api.call("GET", "/products?q=Tee", token=acme_cat)
    verdict(
        "OK",
        "query.search",
        "Text search over declared fields",
        f"?q=Tee -> {body.get('total') if isinstance(body, dict) else body} products (substring match, no ranking or full-text index)",
    )

    # --- things that simply are not there -------------------------------------------------------
    verdict(
        "LIMIT",
        "missing.logic",
        "Checkout, payments, taxes, shipping quotes, discount validation, email notifications",
        "the backend stores rows; every rule above is a service the application must add (populate_commerce.py plays that role)",
    )
    verdict(
        "LIMIT",
        "missing.files",
        "File and image upload",
        "images are URL strings; there is no upload or storage",
    )
    verdict(
        "LIMIT",
        "missing.events",
        "Webhooks, events, background jobs, scheduled work",
        "the Webhook entity only stores configuration; nothing is ever delivered",
    )
    verdict(
        "LIMIT",
        "missing.idempotency",
        "Idempotency keys for retried requests",
        "a retried POST /transactions creates a second transaction (only unique fields protect you)",
    )
    verdict(
        "LIMIT",
        "missing.audit",
        "Change history",
        "only created_by_id exists; no updated_by, no history of who changed a price or a status",
    )
    verdict(
        "LIMIT",
        "missing.tenant_admin",
        "Tenant management",
        "no endpoint to rename or close a store, to move a user between stores, or for a platform operator to see all stores",
    )
    verdict(
        "LIMIT",
        "missing.bulk",
        "Bulk import / batch writes",
        "one row per request: the seed needs ~800 calls; there is no CSV import or batch endpoint",
    )
    verdict(
        "LIMIT",
        "model.polymorphic",
        "Polymorphic relations",
        "Metafield.owner_type/owner_id is just two columns: no foreign key, no referential integrity",
    )
    verdict(
        "LIMIT",
        "model.names",
        "Reserved words",
        "field names such as zip and format, and enum values with '/' or spaces, are refused (renamed in this model)",
    )
    verdict(
        "LIMIT",
        "model.single_inheritance",
        "A role inherits from one parent only",
        "manager cannot inherit from catalog + fulfilment + support; permissions list roles explicitly instead",
    )

    (HERE / "probe_results.json").write_text(
        json.dumps(
            [{"verdict": k, "id": i, "title": t, "evidence": e} for k, i, t, e in results], indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    counts = {k: sum(1 for r in results if r[0] == k) for k in ("OK", "RISK", "LIMIT")}
    print(f"\n{counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
