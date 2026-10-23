# What a Shopify-style backend showed about the platform

A 32-entity commerce model (catalog, variants, inventory, customers, carts, orders, payments, refunds,
fulfilment, discounts, gift cards, shipping, tax, reviews, content, webhooks) was described through the
builder's public API, generated, booted with Docker, filled with two stores' worth of data through real
sign-ups and invitations, and then attacked with `probe_limits.py`. Result: **12 things work as a commerce
backend needs, 10 are risks, 32 are limits.** Every line below comes from a probe or from the generated code;
`probe_results.json` has the raw evidence.

## It worked

- The model validated and generated: 32 entities, 32 relations, 7 roles, 4 custom sign-up fields, 199
  permission rules; 219 files, 78 routes. The generated project passed its **own 156 tests** and its migration
  checks at this size.
- Real flows ran end to end: store sign-up, email verification, invitations that join the inviter's store, roles
  that change what each person may do (catalog editors write products, support opens refunds, fulfilment ships,
  marketing runs discounts, managers configure, customers can read the catalog and write reviews).
- Tenant isolation of rows holds for reads: a store never sees another store's rows, and a forged `tenant_id` /
  `created_by_id` in a request body is ignored.
- Invitations are admin-only. Orders cannot be deleted (the operation is simply not generated). A location that stock
  points to cannot be deleted. Page size is capped. Soft delete, JSON fields, enums, nested collections (a self
  relation) and many-to-many tags/collections all work.
- ~800 API calls seeded 2 stores, 20 users, 18 products (29 variants), 24 customers, 22 orders in every state.

## Fix these first (bugs and security)

| # | Finding | Evidence |
|---|---|---|
| 1 | **A row can point at ANOTHER store's parent.** Foreign keys only check that the id exists, not that it belongs to the caller's tenant. A store can create a variant under another store's product, an order line for another store's variant, link another store's product into its collection, or re-parent an existing row. | `isolation.fk_*` probes: all HTTP 200/201. Reading the foreign row is still blocked, but the link is stored and returned (`product_id` of the injected variant is the foreign id). |
| 2 | **Unique fields are unique across ALL stores.** SKU, discount code, order number, cart token. Store B cannot use order #1001 or code `WELCOME10` if store A did, and a failed attempt tells B that A uses it (information leak). | `unique.*`: HTTP 409 for a value that exists only in another store. This example prefixes every such value with a store key. |
| 3 | **A number too large for its column is a 500**, not a 422. | `money.overflow`: price `99999999999999` gives `internal_error`. |
| 4 | **Secrets in an entity are returned by every read** (no write-only fields). | `content.secrets_readable`: the webhook `secret` is in `GET /webhooks`. |
| 5 | **An operation with no permission is open to every signed-in user.** The builder never warns. The first draft of this model had 6 such holes; `build_commerce.py` now audits for them and refuses to build. | documented behaviour; the audit found `OrderLine.update/delete/replace/head`, `Review.head/replace`. |
| 6 | **Every account gets the default role**, including staff invited with another role. A privileged default role would silently give everyone that access. | staff user roles are `['customer', 'support']`. |

## Limits of the model (what the application must supply)

**Customers and the storefront**
- No public (logged-out) reads: a tenant is resolved from the signed-in user, never from a domain or header, so an
  anonymous storefront cannot read products.
- Customers cannot sign up to an existing store. A sign-up without an invitation creates a **new store**; the only way
  to add someone to a store is an invitation. (This model keeps `Customer` as a data entity, separate from login users.)
- A row rule applies to **every role** listed on an operation. "Customers see only their own orders, staff see all" cannot
  be expressed: `tenant` shows a customer the whole store, `owner` hides orders from staff. Orders and carts are therefore
  staff-only here. (`role_scoped` might help partly, since only the `admin` role would see all and everyone else only what they created; not tried here.)
- Customers also see draft and archived products (no per-role filter).

**Users and roles**
- No user administration: nothing lists a store's staff, changes someone's role, deactivates them or removes them.
- Password reset exists only when email magic links or SMS are enabled (this model had them off, so there is none).
- One login per email across the whole system: an agency person cannot belong to two stores.
- A role inherits from one parent only, and the parent must exist first (creation order matters).
- No tenant management: rename or close a store, move a user, or a platform operator view across stores.

**Integrity and business rules**
- No computed fields or cross-field checks: an order with subtotal 10 and total 1 is accepted. No state machines or
  immutable fields: a cancelled order can be reopened and its number and `placed_at` rewritten.
- No stock logic. Updates are read-modify-write: 8 parallel "take the last item" requests all read stock 1 and all wrote
  0 (a correct system ends at -7 or refuses). There is no atomic increment and no optimistic locking.
- No composite unique constraints (`one inventory level per variant and location`), no per-tenant sequences (order
  numbers), no polymorphic references (`Metafield.owner_id` has no foreign key).
- Money is a fixed `NUMERIC(18,6)`: no currency type, rounding rules or per-field scale (`19.99999999` becomes `20.000000`).
- Soft delete does not cascade (a deleted product's variants are still returned) and a deleted row keeps its unique values.
- HTML is stored verbatim (`<script>` accepted): sanitise in the storefront.

**Querying**
- Exact-match filters on declared fields only: no relation filter (`?customer_id=` is silently ignored, returning all
  rows), no ranges, `in`, or date filters, one sort field, no aggregates or reports (sales per day), no expand: an order
  page costs 1 + N requests (lines, transactions, refunds... come back as id lists).
- Search is substring matching on declared fields, with no ranking or full-text index.

**Not there at all**
- Checkout, payment capture, taxes, shipping quotes, discount validation, emails; webhooks, events, background jobs,
  schedules (the `Webhook` entity only stores configuration); file upload (images are URL strings here; the platform now has a `file` field type and a file API, see the README); idempotency keys;
  change history (only `created_by_id`); bulk or CSV import (one row per request).

**Naming rules found while building**
- Field names cannot be Python builtins (`zip`, `format`); enum values cannot contain `/` or spaces; decimal defaults
  must be numbers; roles must be created parent-first.

## Suggested order of work on the platform

1. Tenant-aware foreign keys: reject a parent from another tenant on create, update and many-to-many writes (and a
   `tenant_id` in the key so the database enforces it). Make unique constraints per tenant.
2. Map numeric overflow to a 422; add write-only (secret) and read-only/immutable fields.
3. Warn in `/validate` about unlisted permissions; stop adding the default role to invited staff.
4. Tenant resolution for storefronts (a store slug on sign-up, a domain/header for anonymous reads) and per-role row rules.
5. User administration endpoints and a password reset that does not depend on magic links.
6. Atomic update (`increment`) and `If-Match` versioning; composite unique; soft-delete cascade with partial unique indexes.
7. Richer queries: relation filters, ranges, `in`, multi-sort, `include=`, and simple aggregates.
8. Later: bulk endpoints, idempotency keys, audit log, outbound webhooks/jobs.

## Reproduce

See `README.md`. `python examples/commerce/probe_limits.py` re-runs every probe (writes happen in a throw-away "lab"
store, so the seeded data is untouched) and refreshes `probe_results.json`.
