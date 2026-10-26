# Agent 2 report — claude-opus-5-5 — 2026-10-26

## Scope accepted
Phase B — Plan enforcement and seat accounting (PLATFORM_SAAS_PLAN §6, §12.B):
1. Transactional quota checks at every §6.2 enforcement point.
2. UI: per-plan usage cards, 402 handling with upgrade CTA.
3. Seat-override field in the operator console.
4. Stripe Checkout endpoint (no webhooks — Phase C).

Inherited a green tree: `tests/api tests/unit` → 1617 passed, 2 skipped (re-run by me
before touching code).

## What was already done
See `agent_1.md`. Corrections to the agent 1 handoff, found by reading the code:
- `POST /projects` did **not** call `_enforce_project_limit` — it was a deferred comment in
  `app/services/project_service.py`. Now wired.
- `accept_invitation` had no seat re-check. Now added.
- The seat check did **not** lock the subscription row (`db.get`, no `FOR UPDATE`), so the
  §6.2 race protection was missing. Now locked.
- **No org frontend existed** (§12.A step 6 was not done). I built only the Plan page
  (`#/org/<slug>/plan`) because Phase B needs it. People / Projects / Invites tabs of the
  org console are still missing — see Open items.

## Research notes
- §6.2 pseudo-code: lock `subscriptions` row `FOR UPDATE`, count members + pending,
  402 with plan and cap. Followed exactly; the lock is held until the write commits.
- §6.2 "Never silently drop; auditors look for the deny log entry" → every 402 writes a
  `quota.denied` audit row (result=`denied`, `organization_id` stamped).
- §6.3: the plan only moves on a Stripe event or by an operator — so Checkout does **not**
  change `subscriptions.plan_id`. It only returns the hosted URL and audits
  `plan.checkout_started` (Stripe session id only, §10).
- Stripe Checkout Session API (`POST /v1/checkout/sessions`, form-encoded, `mode=subscription`,
  `client_reference_id`, `metadata`, `subscription_data[metadata]`, `customer` /
  `customer_email`, `Idempotency-Key` header). No SDK: plain `httpx` (already a dependency).

## Implementation summary

### Backend
- `app/services/organization_service.py`
  - `_locked_plan_and_subscription()` — `SELECT … FOR UPDATE` on the subscription row;
    missing subscription fails closed (404), never "unlimited".
  - `_deny()` — rollback, write `quota.denied` audit (resource/plan/cap/used), commit, return
    a 402 `AppError` whose `details[0]` = `{resource, plan, cap, used, organization_slug}`.
  - `enforce_seat_limit(extra=…)`, `enforce_project_limit()`, `enforce_token_limits()` —
    public (were private `_enforce_*`). Codes: `seat_limit`, `project_limit`,
    `api_token_limit`, `mcp_token_limit`.
  - `count_active_tokens(org, user_id=?, mcp_only=?)` — **token→org rule**: a token pinned
    to a project belongs to that project's org; an unpinned token belongs to its owner's
    `default_organization_id`. MCP tokens = JSON `scopes` text contains `"mcp:`.
  - `create_invitation` — seat check moved **out of** the savepoint (a denial must roll back
    and commit its audit row; can't do that inside `begin_nested`).
  - `accept_invitation` — seat re-check with `extra=0` (the invite is already counted as
    pending), skipped if the user is already a member.
  - `usage(viewer_id=…)` — adds `api_tokens_used` (viewer's own), `api_tokens_cap`,
    `mcp_tokens_used`, `mcp_tokens_cap`.
- `app/services/project_service.py` — calls `enforce_project_limit` before insert.
- `app/services/api_token_service.py` — `_enforce_plan_limits()` resolves the org (rule
  above) and enforces API + MCP caps. The old global `MAX_ACTIVE_TOKENS_PER_USER=25` (409)
  stays as a platform-wide ceiling.
- `app/services/stripe_client.py` (new) — `create_checkout_session()` over `httpx`;
  `StripeError`; injectable `transport` for tests.
- `app/services/billing_service.py` (new) — `BillingService.start_checkout()` and
  `upgrade_options()`; `checkout_available()`. Order of checks: plan exists (404) → not the
  current plan (409) → Stripe configured (503 `billing_unavailable`) → purchasable (422
  `plan_not_purchasable`: public, priced, has a configured Price) → Stripe call (502
  `billing_provider_error`, Stripe text logged, never returned).
- `app/api/orgs.py` — `POST /orgs/{slug}/billing/checkout` (admin/owner, 201
  `{id, url}`); `GET /orgs/{slug}/plan` now also returns `checkout_available` and
  `upgrades` (purchasable plans other than the current one).
- `app/schemas/organization.py` — `OrgUsage` token fields, `OrgPlanRead.checkout_available`
  / `upgrades`, `CheckoutCreate`, `CheckoutRead`.
- `app/config.py` — `stripe_secret_key`, `stripe_price_ids` (plan id → Price id; kept in
  config so the §3 `plans` schema is unchanged), `public_app_url`. Documented in
  `.env.example`.
- **No migration** in Phase B.

### Frontend
- `api/types.ts` — `Organization`, `PlanInfo`, `OrgUsage`, `OrgPlan`, `QuotaDetail`, `AdminOrg`.
- `api/client.ts` — `listOrgs`, `orgPlan`, `startCheckout`, `adminOrganizations`,
  `adminSetOrgOverrides`; every 402 is broadcast via `onQuotaExceeded()`.
- `components/QuotaPrompt.tsx` (new) — global modal on any 402: "The free plan includes 1
  projects…", **See plans** → `#/org/<slug>/plan`. Mounted in the customer app and workspace.
- `pages/OrgPlanPage.tsx` (new) — plan header + status, `past_due` banner, four usage cards
  (seats incl. pending, projects, your API tokens, org MCP tokens; amber ≥80 %, red when
  full), upgrade cards → Stripe Checkout redirect; handles `?checkout=success|cancel`.
  Non-admins see "ask an owner or admin".
- `App.tsx` — `#/org/<slug>[/plan]` route. `components/Sidebar.tsx` — "Plan & usage" list of
  the user's orgs.
- `pages/admin/AdminApp.tsx` + `AdminPages.tsx` — new **Organizations** tab: plan, status,
  members, projects, overrides; **Limits** dialog edits seat/project override with a required
  reason (uses agent 1's audited `PATCH /admin/organizations/{id}/overrides`). Hidden for
  read-only support staff.
- `index.css` — `.stat-card.status-error`, progress bar in stat cards.

### Tests infrastructure
- `tests/api/conftest.py` — new autouse `_unlimited_personal_plan`: test users' personal orgs
  start on `enterprise` (uncapped). **Why:** with enforcement live, free = 1 project and 0 MCP
  tokens, which would break ~dozens of feature tests that create several projects / MCP
  tokens. Quota tests set the plan they need explicitly. Production sign-ups still get `free`.

## Tests I wrote (TDD evidence)
Written first, observed red, then implemented.
- `tests/api/test_plan_enforcement.py` (12): project cap + audit; project override; API token
  cap per user per org + revoke frees slot; pinned token charged to the project's org; MCP cap
  on free = 0 with plain tokens still allowed; MCP cap shared across members; accept re-checks
  seat cap (and passes after raising it); invite denial audited; **concurrent invites** (5
  parallel, cap leaves 1 → exactly one 201); **concurrent project creates** (4 parallel, cap 1
  → exactly one 201); usage reports every counter; missing subscription fails closed.
  - Verified the concurrency tests are meaningful: with `with_for_update()` removed both fail.
- `tests/api/test_billing_checkout.py` (13): admin starts checkout (args, URLs, plan unchanged,
  audit detail); existing Stripe customer reused; members get 403; free/enterprise/current/
  unknown plans refused with no Stripe call; 503 when unconfigured; 502 without leaking Stripe
  text; Stripe client form/auth/idempotency via `httpx.MockTransport`; client raises on 4xx;
  plan page lists upgrades / empty without Stripe.

## Test run result
```
tests/api tests/unit  →  1642 passed, 2 skipped, 58 warnings in 195.09s
(baseline 1617 + 25 new; 2 skips and 58 Starlette 422 deprecation warnings are pre-existing)
```
Frontend: `tsc -b` clean, `vite build` OK, `oxlint` — no new warnings except the
repo-wide "setState in effect" pattern on `OrgPlanPage` load (same as existing panels).
E2E (`tests/e2e`) not run — it needs the Docker Compose stack and hangs without it.

## Improvement scope — out of current phase
- **Free plan seeds are strict for existing users.** Agent 1 seeded free = 1 project,
  3 API tokens, 0 MCP tokens. With Phase B live, any backfilled user who already has >1
  project can't create another, and free users can't create MCP tokens at all (the WP6
  feature). That matches §6.3 "soft-fail existing, hard-fail new", but it's a product call —
  **the owner should confirm the free-plan numbers before deploy** (editable via
  `PUT /admin/plans/free`, no code change).
- **Team orgs are created on the paid `team` plan for free** (`DEFAULT_TEAM_PLAN_ID`). Phase C
  should start them as `trial` (or `free`) and let Checkout/webhook move them to `team`.
- **`plans.allow_mcp` isn't checked separately**; the MCP counter (cap 0 on free) does the job
  today. If a plan ever has `allow_mcp=false` with a non-zero cap, add an explicit check.
- **Seat quantity at checkout = current members.** §6.4 high-water-mark billing and
  quantity sync on membership change belong to Phase C step 4.
- **`past_due` soft-fail** (§10: block new seats/projects) is not enforced yet — Phase C step 5.
  The UI banner is already in place.
- Agent 1's `app/api/orgs.py` has a few ruff findings (unused imports `request_info`,
  `AppError`; `AccountStatus` unused in the org service; B008 on `Path`). Left untouched.
- Audit `quota.denied` rows are created inside the user's request session after a rollback.
  If Phase F adds RLS, make sure the audit insert is allowed under the bound org.

## Open items / known issues
- **Org console is incomplete** (Phase A step 6 leftover): no People, Invites, Projects tabs,
  no "accept invitation" UI. `#/org/<slug>` currently lands on the Plan tab. Whoever picks
  this up: routes are in `App.tsx` (`page: 'org-plan'`), API calls already exist server-side.
- Admin Plans tab (§7) and org detail / audit tail still have no frontend.

## HANDOFF: continue at Phase C.1 — read PLATFORM_SAAS_PLAN.md §6.3, §10, §12.C, then agent_2.md "Improvement scope"

Phase C is **Stripe automation**. What's ready for you:
- `app/services/stripe_client.py` — add the webhook signature verifier and the
  subscription-item quantity update here (keep `httpx`, no SDK).
- Checkout already sends `client_reference_id`, `metadata[organization_id|plan_id]` and
  `subscription_data[metadata][organization_id|plan_id]`, so `checkout.session.completed`
  and `customer.subscription.updated` can be mapped back to the org.
- `subscriptions.stripe_customer_id / stripe_subscription_id` exist but nothing writes them
  yet — the webhook should (Checkout reuses `stripe_customer_id` when set).
- Return URL is `#/org/<slug>/plan?checkout=success|cancel`; the page already shows a toast.
- Quota checks all go through `OrganizationService.enforce_*` — the `past_due` hard-fail for
  new seats/projects (Phase C.5) is one check inside `_locked_plan_and_subscription` callers.
- Config: `BUILDER_STRIPE_SECRET_KEY`, `BUILDER_STRIPE_PRICE_IDS`, `BUILDER_PUBLIC_APP_URL`;
  you'll need a `BUILDER_STRIPE_WEBHOOK_SECRET`.
