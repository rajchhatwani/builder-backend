# Agent Orchestration — Trigger & Handoff Log

> **This file is the orchestration baton.** When you (an agent) start a session, read this
> file first, then read `/mnt/files/projects/builder-backend/platform_implementation_agents/`
> for the latest numbered agent report (`agent_1.md`, `agent_2.md`, …). Then open the plan
> at `PLATFORM_SAAS_PLAN.md` and continue from the next **unfinished** phase/step.

## Mission (do not re-plan)

Implement `PLATFORM_SAAS_PLAN.md` end-to-end, in phase order **A → F**:

- Phase A — Organizations core (migration + models + service + /orgs API + admin ext + UI)
- Phase B — Plan enforcement & seat accounting
- Phase C — Stripe automation
- Phase D — Enterprise SSO (SAML + OIDC per org)
- Phase E — SCIM 2.0
- Phase F — Hardening (RLS, pen test, impersonation, SOC 2 evidence)

The plan is authoritative. Do **not** redesign. Do **not** second-guess the schema in §3,
roles in §2.2, or quota approach in §6. If you find a genuine issue, write it in your agent
report under "Improvement scope — out of current phase" instead of silently diverging.

## The TDD cycle every agent follows

Red → Green → Refactor, **per unit**:

1. Pick the next step in the current phase.
2. Write a failing test that would pass only when the step is implemented
   (`tests/api/test_*.py` is the primary location; add `tests/unit/*.py` for pure services).
3. Implement the smallest change that makes the test pass.
4. Repeat for the next unit of behavior.
5. When finishing a phase: rerun the entire test suite (`uv run pytest -q`) and confirm
   zero regressions before writing your handoff.

## Code conventions in this repo

- Python 3.12, FastAPI, SQLAlchemy 2 async, Pydantic v2, Alembic.
- Services raise `AppError(code, message, status_code)`; FastAPI handlers translate.
- `AsyncSession` is injected via `Depends(get_session)`.
- Models live in `app/models/`, schemas in `app/schemas/`, services in `app/services/`,
  routes in `app/api/`.
- Every write-path mutates audit via `app.services.audit_service.record`. **Never log raw
  tokens, passwords, or spec content.** Audit `detail` sanitizer strips keys matching
  password/token/secret/authorization/cookie/otp.
- Alembic revision IDs are 12-char hex. Chain `down_revision` to the previous head.
- Tests use `conftest.py` fixtures: `client`, `client_for`, `make_user`, `anon_client`.
  Postgres is spun up by testcontainers unless `TEST_DATABASE_URL` is set.
- Run tests with `uv run pytest -q` from repo root. Fast mode shaves cost: scrypt N is
  lowered automatically in the autouse fixture.

## Current status

### Agent 1 — DONE (Phase A). Report: `platform_implementation_agents/agent_1.md`
### Agent 2 — DONE (Phase B). Report: `platform_implementation_agents/agent_2.md`

### Agent 3 — DONE (Phase C). Report: `platform_implementation_agents/agent_3.md`

### Agent 4 — YOU ARE UP: Phase D (Enterprise SSO — SAML + OIDC per org)
Start at **Phase D.1** (migration: `sso_connections`, `sso_domains`). Read, in order:
1. `platform_implementation_agents/agent_1.md`, `agent_2.md`, `agent_3.md` (agent 3's HANDOFF
   section lists what's ready for Phase D: `plans.allow_sso` gate pattern, crypto, alembic head).
2. `PLATFORM_SAAS_PLAN.md` §4.2, §6.2 (SSO row), §12.D.

Inherited tree: `uv run pytest tests/api tests/unit -q` → **1689 passed, 2 skipped**.
Run `tests/api tests/unit` only — `tests/e2e` needs the Docker Compose stack and hangs
without it. Alembic head is `b2c3d4e5f6a7` (Phases B and C added no migration).

Conventions so far: `tests/api/conftest.py::_unlimited_personal_plan` puts test users'
personal orgs on uncapped `enterprise`; quota/billing tests set the plan they need. Stripe is
always faked in tests (monkeypatch `app.services.stripe_client.*`). Unauthenticated routes must
be added to `PUBLIC` in `tests/api/test_access_matrix.py` (agent 3 did this for the webhook).

When finishing: write `agent_4.md`, append a line under "Previous handoffs", and point the
final HANDOFF line at Phase E.

### Agent report format (`agent_<N>.md`)

```
# Agent <N> report — <model id> — <ISO timestamp>

## Scope accepted
<which phase/steps I owned when I started>

## What was already done
<bullet list of code/tests landed by prior agents, cross-referenced to files>

## Research notes
<external patterns I checked, decisions I confirmed from the plan>

## Implementation summary
<file-by-file what I changed, with brief motivation; focus on surprises>

## Tests I wrote (TDD evidence)
<paths of test files and what they cover>

## Test run result
<paste the final `pytest -q` summary line and anything red/flaky>

## Improvement scope — out of current phase
<things I noticed but DID NOT change because they belong to a later phase or a different concern>

## Open items / known issues
<anything I know is still broken and why>

## HANDOFF: continue at <phase.step> — read <file(s)> first
```

## Do and don't

- **Do** keep every commit test-first. **Do** run `uv run pytest -q` before writing handoff.
- **Do** make backfill migrations idempotent and reversible where possible.
- **Don't** change the Keycloak code (that's the generated-project auth, not Builder auth).
- **Don't** introduce new dependencies without noting them in your agent report.
- **Don't** delete prior agent reports.
- **Don't** touch other branches or push remotes. Operate on `need_review_before_merge` and
  commit when the user asks — otherwise leave work in the working tree.

## Previous handoffs (append below as agents finish)

- **Agent 1 → Agent 2** (2026-10-26, opus-4.7): Phase A backend complete (orgs, members,
  invites, plans, subscriptions, admin ext). 1617 tests green. Phase A step 6 (frontend
  UI) deferred to a frontend slot; Phase B is the next phase in order.
- **Agent 2 → Agent 3** (2026-10-26, opus-5-5): Phase B (locked quota checks + `quota.denied` audit at
  every §6.2 point, accept-time seat re-check, API/MCP token caps per org, Stripe Checkout
  endpoint without webhooks, Plan & usage page, global 402 upgrade prompt, admin Organizations
  tab with seat/project overrides) — 1642 passed. → Phase C.1.
- **Agent 3 → Agent 4** (2026-10-26, opus-5-5): Phase C (signed Stripe webhook at
  `POST /billing/stripe/webhook` syncing plan/status/period/ids — idempotent, order-safe, customer-
  and replaced-subscription-guarded; one subscription per org via 409 on second Checkout + Billing
  Portal endpoint; high-water-mark seat sync on invite accept, reset at renewal; `past_due` blocks
  new seats/projects with 402 `subscription_past_due`; "Manage billing" UI) — 1689 passed. → Phase D.1.
