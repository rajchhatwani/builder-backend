# Agent 3 report — claude-opus-5-5 — 2026-10-26

## Scope accepted
Phase C — Stripe automation (PLATFORM_SAAS_PLAN §6.3, §6.4, §10, §12.C), all five steps:
1. Stripe Customer + Subscription per org.
2. Checkout session, success and cancel URLs.
3. Webhook with signature verification; sync `subscriptions` on `checkout.session.completed`,
   `customer.subscription.updated`, `invoice.payment_failed`.
4. Seat sync on membership change (`subscription_item.quantity`).
5. Soft/hard fail on `past_due`.

Inherited tree, re-run by me before touching code: `tests/api tests/unit` → 1642 passed, 2 skipped.

## What was already done
See `agent_1.md` and `agent_2.md`. From agent 2, used as-is:
- `stripe_client.create_checkout_session` (httpx, no SDK) — already sends `client_reference_id`
  and `metadata[organization_id|plan_id]` on the session and the subscription.
- `BillingService.start_checkout` with success/cancel URLs → `#/org/<slug>/plan?checkout=…`.
  **Step C.2 was therefore already done**; I added only the "already subscribed" guard below.
- `subscriptions.stripe_customer_id / stripe_subscription_id` columns (Phase A) — nothing wrote
  them before this phase; the webhook now does.

## Research notes
- Stripe signature scheme: `Stripe-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "t.body")>`,
  several `v1` allowed, tolerance window against replay. Same algorithm as the generator's
  own `app/core/generator/features/payments/templates/.../providers/stripe.py.tpl`; I mirrored its
  constant-time "compare every pair" loop and header limits.
- Stripe does not guarantee delivery order and retries for days → handlers are idempotent
  (event id dedupe) and order-safe (older `created` never overwrites newer).
- API-version drift handled: `current_period_end` is on the subscription **item** in 2025+ API
  versions (top-level in older ones); an invoice's subscription id is
  `parent.subscription_details.subscription` in 2025+ (top-level `subscription` before). Both
  shapes are read and both are tested.
- High-water-mark seats (§6.4): mid-cycle the quantity only rises (prorated); it resets to the
  current members at the start of a new period (no proration).
- Billing Portal (`POST /v1/billing_portal/sessions`) is Stripe's hosted page for plan change,
  card update and cancel. Its changes come back as `customer.subscription.*` webhooks.

## Implementation summary

### Backend
- `app/config.py` — `stripe_webhook_secret` (comma-separate two during a secret roll),
  `stripe_webhook_tolerance_seconds` (300), helper `stripe_webhook_secrets()`. `.env.example`
  documents them plus the five events to subscribe the endpoint to.
- `app/services/stripe_client.py` — refactored the HTTP call into `_call()`; added
  `verify_webhook()` (pure; nothing parsed before the HMAC passes), `WebhookSignatureError`,
  `get_subscription()` → `SubscriptionInfo(id, item_id, quantity)`, `set_item_quantity()`,
  `create_portal_session()`. Still no SDK.
- `app/services/stripe_webhook_service.py` (new) — `StripeWebhookService.handle(event)`:
  - **Org mapping**: checkout → `client_reference_id`/metadata; subscription/invoice → stored
    `stripe_subscription_id` first, then metadata, then stored `stripe_customer_id`.
  - Locks the subscription row `FOR UPDATE` → concurrent deliveries for one org serialize.
  - **Dedupe**: the audit row's `target_type='stripe_event', target_id=<event id>` *is* the
    processed-events log (no new table — §3 schema unchanged).
  - **Ordering**: events older than the newest applied one for the org → `stale`, recorded, not applied.
  - **Customer guard**: an event naming a different Stripe customer than the org's → `customer_mismatch` (audit result `denied`).
  - **Replaced-subscription guard**: events from a subscription other than the org's live one
    (cancel → buy again → late event from the old sub) → `other_subscription`, not applied.
  - checkout completed + paid → plan from metadata, status `active`, ids stamped; unpaid (async
    payment) → ids stamped, plan unchanged.
  - subscription created/updated → status map (`trialing→trial`, `past_due|unpaid|paused→past_due`,
    `canceled|incomplete_expired→canceled`, `incomplete`→unchanged), plan from the Price id
    (reverse of `BUILDER_STRIPE_PRICE_IDS`) **only while the sub is live**, `trial_ends_at`,
    `current_period_end`; reports `period_renewed` when the period end advances.
  - subscription deleted / canceled → status `canceled`, plan → `free`.
  - invoice.payment_failed → `past_due` (only from active/trial).
  - Plan moved below current usage → `plan.over_cap` audit (§6.3) with seats/projects used vs cap.
  - Audit `billing.stripe_event` holds event id/type/created, outcome, our plan/status. No
    customer email, no card data (§10). `via='stripe'`, no actor.
- `app/api/billing.py` (new) — `POST /billing/stripe/webhook`, unauthenticated, 256 KB cap,
  503 when no secret configured, generic 400 `invalid_webhook` on any verification failure
  (reason logged only), 200 `{received, outcome}` for applied *and* deliberately skipped events
  (so Stripe stops retrying); unexpected errors → 5xx → Stripe retries, safely.
  Registered in `app/main.py`.
- `app/services/billing_service.py`:
  - `start_checkout` refuses 409 `already_subscribed` when the org has a live Stripe subscription
    (active/trial/past_due) → never a second subscription (§10). Canceled orgs can buy again and
    reuse the same Stripe Customer.
  - `start_portal()` — 503 unconfigured, 409 `no_billing_account` without a customer, 502 on
    Stripe failure; audits `billing.portal_opened`.
  - `sync_seats(org_id, new_period=False)` — C.4. Billed seats = members (not pending invites).
    Best effort after the membership commit; Stripe failure → log + `billing.seat_sync_failed`
    audit (result `error`), never blocks the join. Success → `billing.seats_synced {from,to}`.
  - `LIVE_STATUSES`, `has_live_stripe_subscription()`, `portal_available()`.
- `app/api/orgs.py` — `POST /orgs/{slug}/billing/portal` (admin/owner, 201 `{url}`);
  invitation accept calls `sync_seats` after commit; `GET /orgs/{slug}/plan` returns
  `portal_available`.
- `app/schemas/organization.py` — `PortalRead`, `OrgPlanRead.portal_available`.
- `app/services/organization_service.py` — C.5: `_refuse_if_past_due()` inside
  `enforce_seat_limit` and `enforce_project_limit` (after the row lock) → 402
  `subscription_past_due`, on every plan including uncapped ones. Reuses `_deny`, which now takes
  `cap: int | None` and writes `reason: 'cap' | 'past_due'` into the audit detail and the 402
  details. Token creation is **not** blocked (§10 names only seats and projects). Added public
  `count_members()`.
- **No migration** in Phase C.

### Frontend
- `api/types.ts` — `OrgPlan.portal_available`; `QuotaDetail.cap: number | null`, `reason`.
- `api/client.ts` — `openBillingPortal(slug)`.
- `pages/OrgPlanPage.tsx` — **Manage billing** button (owners/admins, when the org has a Stripe
  customer) → Stripe Billing Portal; paying orgs see "change plan under Manage billing" instead
  of Checkout cards; the `past_due` banner says how to fix it.
- `components/QuotaPrompt.tsx` — a `past_due` 402 shows "Payment needed" instead of "Plan limit reached".
- `tsc -b` clean, `vite build` OK, `oxlint` no new warnings (the `set-state-in-effect` one on
  `OrgPlanPage` load is agent 2's, pre-existing).

### Tests infrastructure
- `tests/api/test_access_matrix.py` — added `("POST", "/billing/stripe/webhook")` to `PUBLIC`
  (authenticated by signature, not session). Required, deliberate.

## Tests I wrote (TDD evidence)
Written first and observed red (17/17 webhook tests failed, the other two files failed to
import), then implemented. Mutation-checked: disabling the dedupe, the stale-order check or the
customer guard each makes its test fail.
- `tests/unit/test_stripe_signature.py` (15) — valid, multiple signatures/secrets (rotation),
  8 malformed headers incl. oversized, wrong secret, altered body, ±tolerance, no secret, non-JSON body.
- `tests/api/test_billing_webhooks.py` (20) — rejected deliveries change nothing and leak
  nothing; 503 unconfigured; rotated secrets; checkout applies plan + ids + audit without PII;
  unpaid checkout; redelivery once; **4 concurrent redeliveries → exactly one applied**;
  unknown org; customer mismatch; unhandled types; subscription updated (trial → active,
  plan by price, period); lookup by stored sub id without metadata; deleted → free; stale
  ordering; downgrade below usage → `plan.over_cap` + new invite 402; payment failed in both
  invoice shapes; `incomplete` doesn't unlock a plan; replaced-subscription events ignored;
  past_due blocks invites, invite accept and projects (402 + `quota.denied` reason past_due)
  while reads keep working.
- `tests/api/test_billing_seats.py` (12) — join raises quantity with proration + audit;
  high-water mark (no drop mid-cycle, removal doesn't call Stripe); Stripe outage doesn't block
  the join and is audited without secrets; no Stripe sub / canceled sub → no sync; renewal
  resets to members with no proration; paying org gets 409 on second checkout; canceled org can
  buy again with the same customer; portal for admins, 409 without customer, 403 for members;
  stripe client GET/POST shapes for subscription, item and portal.

## Test run result
```
tests/api tests/unit  →  1689 passed, 2 skipped, 58 warnings in 232.51s
(baseline 1642 + 47 new; 2 skips and 58 Starlette 422 deprecation warnings are pre-existing)
```
E2E (`tests/e2e`) not run — needs the Docker Compose stack.

## Improvement scope — out of current phase
- **Team orgs still start on the paid `team` plan for free** (agent 2 flagged it). This now has a
  visible effect: a new team org can't "buy" Team (Checkout refuses the current plan), only
  Business. Product call for the owner: start team orgs on `free`/`trial` and let Checkout move
  them, or allow checkout of the current plan when there's no Stripe subscription. I did not
  change it: existing Phase A/B tests encode the current behaviour and it's not in §12.C.
- **Subscription cancel → `free` plan.** §6.3/§10 don't say which plan a canceled org falls to;
  `free` is the only safe default (keeps paid caps from outliving payment). Usage above the free
  caps is soft-failed per §6.3 and audited as `plan.over_cap`.
- **Webhook dedupe lives in the audit log** (target_id = event id). There's no index on
  `platform_audit_log.target_id`; at volume add `(action, target_id)` index (Phase F) — a
  migration, so I left it.
- **No reconciliation job.** A lost webhook (Stripe gives up after ~3 days) leaves the row stale.
  A periodic "fetch subscription from Stripe and re-apply" job would close it; the generator's
  payments feature has a `reconcile.py` pattern to copy.
- **`livemode` isn't checked.** A test-mode event signed with the live secret can't happen (each
  mode has its own secret), but an explicit check against the key prefix would be belt-and-braces.
- **Seat removal doesn't call Stripe** (high-water mark): the leaver drops off at renewal. If the
  owner prefers immediate credit, call `sync_seats(..., new_period=True)`-style decreases on remove.
- **Quantity sync is synchronous in the accept request** (one GET + maybe one POST to Stripe, 15 s
  timeout). Fine at current scale; move to a background job if accept latency matters.
- **SCIM create (Phase E)** must call `BillingService.sync_seats(org_id)` after it commits, like
  invitation accept does.
- Agent 2's ruff findings in `app/api/orgs.py` are still there (untouched).

## Open items / known issues
- **Stripe Dashboard setup is manual**: create the webhook endpoint at
  `<api>/billing/stripe/webhook` with the five events in `.env.example`, set
  `BUILDER_STRIPE_WEBHOOK_SECRET`, and enable the Customer Portal (plan switching between the
  Team/Business prices) in Stripe → Settings → Billing → Customer portal.
- Org console People / Invites / Projects tabs (Phase A step 6 leftover) are still missing —
  unchanged from agent 2's note.
- Not verified against a real Stripe account (no keys in this environment); all Stripe calls are
  faked in tests. First deploy should use `stripe listen --forward-to` / `stripe trigger` to
  replay real event shapes.

## HANDOFF: continue at Phase D.1 — read PLATFORM_SAAS_PLAN.md §4.2, §6.2 (SSO row), §12.D, then agent_3.md "Improvement scope"

Phase D is **Enterprise SSO (SAML + OIDC per org)**. What's ready for you:
- `plans.allow_sso` is seeded (business/enterprise = true) — §6.2 says gate SSO connection
  create/activate on it, with the same 402 + `quota.denied` pattern (`OrganizationService._deny`,
  pass `cap=None` and a `reason`, e.g. `'feature'`; the frontend `QuotaDetail.reason` union will
  need that value added).
- `sso_connections` / `sso_domains` tables are in §3 but **not yet migrated** — D.1 is that
  migration. Alembic head: check `alembic heads` (Phase A's `b2c3d4e5f6a7` is the last one; Phases
  B and C added none).
- `oidc_client_secret_enc` must use the existing `auth_secrets` envelope crypto (`app.core.crypto`).
- Audit: never put IdP certs or client secrets in `detail` (the sanitizer only strips keys named
  like password/token/secret).
