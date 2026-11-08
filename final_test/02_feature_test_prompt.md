# Session 2 — final FEATURE test (whole stack, break it)

Paste the block below into a NEW session. Session 0 (the credentials setup) is finished and the environment is prepared (final_test/SESSION_HANDOFF.md). Run this session AFTER session 1 (security), never in parallel (they share one ngrok domain, one Okta tenant, one Stripe test account and one mailbox). It can run in parallel with session 1 only if you give each its own ports and its own throwaway database; otherwise run it after.

```
PREPARED ENVIRONMENT (read before anything else)
Read final_test/SESSION_HANDOFF.md first, then final_test/credentials/NOTES_FOR_TEST_SESSIONS.md and TEST_ACCOUNTS.md. Everything the
user could do for you is already done: stack scripts, DB snapshot, credentials (env file: ~/final_test.env), staff TOTP, test
accounts, real Okta/Stripe-test/SMTP/DNS/ngrok, headless-Chrome helpers. You must be fully autonomous: NEVER stop to ask the user a
question. If something cannot be done, record "could not test: <reason>" in your report and continue. Start with:
  final_test/harness/stack.sh restore configured && final_test/harness/stack.sh up production && final_test/harness/stack.sh status
Use final_test/harness/bb.py (sign in as any role, staff TOTP, read the real inbox, act as a SCIM client, send signed Stripe events).
The harness may write to final_test/logs, final_test/run and ~/bb_snapshots in addition to the directory named below.

You are the final feature/QA tester for Backend Builder in /mnt/files/projects/builder-backend (FastAPI backend + React frontend: project builder and code generator, organizations, plans/quotas/seats, Stripe billing, enterprise SSO SAML/OIDC, SCIM, TOTP MFA, org policies, operator console, MCP). This is the last test before real credentials go live. Your only job is to prove every feature works end to end through the real UI and API, and to BREAK it with edge cases. Do not stop at the first failures and do not give general advice, only evidence.

Hard rules
- Do NOT change product code (app/, alembic/, frontend/src/, existing tests/). Do not commit, push or touch other branches. Do not change Keycloak code. Do not delete other agents' reports.
- Write only inside final_test/features/ (report, scripts, screenshots, logs). Create it. Everything must be re-runnable.
- Use a throwaway Postgres only; never a real/production database. Use the real third-party systems (Stripe test mode, IdP, SMTP inbox, DNS, storage) through the filled env file ~/final_test.env (never print it), test/sandbox mode only. Never print, log or write any raw token, password, secret, cookie or recovery code — redact in all files and screenshots.
- Sessions run one after the other (they share the ngrok domain, Okta, Stripe and the mailbox): use the harness default ports; do not use port 5173.

Read first
PLATFORM_SAAS_PLAN.md; review/review_PLATFORM_SAAS_PLAN.md (prior audit and its scripts in review/tests); agent-orch/trigger_and_report_here.md; platform_implementation_agents/agent_*.md; agent-orch/*.md; README.md; final_test/credentials/TEST_ACCOUNTS.md; app/config.py.

Bring up the full stack: final_test/harness/stack.sh `up production` (Postgres, migrations, built frontend, one proxy origin for app+API, API, ngrok tunnel); start Redis/MinIO-compatible/Keycloak/OTLP with docker only if features need them (defaults in the env file). For bulk invite/mail runs use `MAIL=sink` (Mailpit) and keep real-mailbox mails under ~25 in total; verify real delivery (also the Spam folder) with bb.wait_mail. Drive the UI with a real browser automation (Chrome is at /usr/bin/google-chrome-stable; install puppeteer-core or playwright OUTSIDE the project, e.g. in a scratch dir) and drive the API directly in parallel. Record what you could not stand up.

Journeys to execute for EVERY role — anonymous, individual (personal org), org owner, org admin, org member, outsider from another org, platform admin, platform support — each journey with happy path, wrong-role path, and edge cases:
1. Sign-up, login (e-mail-first with SSO discovery), logout, refresh, password change, forced password change, e-mail case/Unicode variants, rate limit and lockout messages, back/refresh/double-click behaviour.
2. Account: profile, API tokens (create, scopes, project-pinned, revoke, quota), TOTP enrol/disable, recovery codes, org-required MFA prompt.
3. Projects: create, list, rename, delete, move between orgs, members and project roles, viewer/editor/owner limits, locked-org behaviour.
4. Builder core: entities, fields, relations, auth config, custom fields, permissions/roles, authorization policies and simulator, storage, payments, deployment, observability, documents, Keycloak settings, spec validation, generate preview/download/zip — then actually BUILD and RUN a generated project from at least three specs (simple CRUD, auth+roles, payments/documents/storage if configured), run its own tests, and hit its endpoints. Try hostile specs (empty, huge, reserved words, duplicate names, Unicode, SQL keywords, circular relations, 1000 fields) and check the generator fails cleanly.
5. Organizations: create team org, rename, invite (e-mail actually arrives in the SMTP inbox, link works, expired, revoked, resend, wrong account, accept by id), roles change, remove, leave, transfer ownership, last-owner rules, delete request with grace period, cancel, operator change-period / delete-now, scheduled deletion executed (run the job) and data really gone, org switcher, breadcrumbs.
6. Plans & quotas: every limit at n and n+1 (seats incl. pending invites, projects, API tokens, MCP tokens), concurrent attempts for the last slot, downgrade over limit, operator overrides, trial expiry, 402 prompts in the UI with the right resource names, plan flags (SSO, SCIM, MCP) really enforced.
7. Stripe (real test mode; no webhook endpoint is registered at Stripe and you must not create one: use bb.stripe_webhook for signed events and `~/.stripe/bin/stripe listen/trigger` if it works): checkout for team and business, webhook arrives and plan changes, seat quantity sync on invite accept and SCIM create, billing portal, payment failure (use Stripe test card for declines) -> past_due banner and blocks, recovery, cancellation -> free, replayed/duplicate/out-of-order events (stripe CLI resend/trigger), reconcile job.
8. SSO (real Okta where its password allows it, else the synthetic IdP/Keycloak fallbacks of SESSION_HANDOFF §4; you cannot add DNS records: `dumbpotato.com` is already verified for org bb-sso): domain add + real DNS TXT verification, SAML and OIDC setup in the UI, test-with-my-email, activate, discovery on the login page, login via IdP, JIT provisioning with role setting, seat cap, existing accounts, staff refused, unverified/foreign domains, deactivate, downgraded plan fallback, error banners (sso_error) for every failure reason you can trigger.
9. SCIM (the real Okta push already worked once during setup: create, group role map, deactivate; test the rest by acting as the IdP with bb.Scim): token shown once, base URL, IdP test connection, create/update/deactivate/reactivate/delete users, groups and role mapping, owner-mapping rule, seat sync, offboarding side effects (sessions, tokens, project handover), pagination, rotate token, operator rotate then fresh token, People table state, audit entries.
10. Org policies: require MFA (enable/disable edge cases), session TTL honoured by real refresh behaviour, audit tab content and pagination, member views are read-only with "ask <owner>" messages.
11. Operator console: login with mandatory MFA enrolment, people, orgs (detail, overrides, deletion, SSO check, SCIM column and rotate), plans (edit, validation), billing, insights, audit filters, projects metadata only, support role read-only, "customer app" link.
12. MCP: enable per project/member, token scopes, tool calls, org policy interaction, quotas.
13. Phase F features if present (impersonation with banner/consent/write-block, per-org export, RLS flag on and off, docs): test them fully; if absent, say so.
14. Cross-cutting UX: every error code (401, 402, 403, 404, 409, 422, 423, 429, 5xx) produces a clear UI message; loading/empty/error states; narrow (375px), tablet, desktop; dark mode; keyboard use; browser back/forward/refresh on every page; two tabs/sessions; slow network and offline; long strings, Unicode/emoji, HTML in names; page text matches real backend behaviour; frontend types match OpenAPI (run review/tests/types_drift.py).
15. Data & ops: migration upgrade/downgrade with real data, restart persistence, background jobs (deletion, reconcile) run manually, health/ready endpoints, logs free of secrets, performance sanity (list endpoints with 5000 rows, pagination limits).

Edge-case discipline: for each feature also try empty/null/duplicate/max-length/negative/huge values, concurrency (parallel clicks and requests), stale pages, expired links, clock skew, partial failures (kill the DB or Stripe mid-request), and out-of-order flows.

Method: automate each journey as a re-runnable script under final_test/features/journeys/ (API) and final_test/features/ui/ (browser), save redacted screenshots to evidence/, and for each failure write a minimal reproducer. Anything you could not reproduce is "suspected".

Deliverables in final_test/features/
- FEATURE_REPORT.md: 1) verdict (3–5 lines, go/no-go for attaching real credentials), 2) environment and what could not be tested and why, 3) failures ranked Blocker/Major/Minor/Cosmetic — each with ID, feature, steps to reproduce (script path), expected vs actual, screenshot, suggested fix, 4) coverage matrix (journey x role -> pass/fail/not tested), 5) results of the three generated-project builds, 6) things checked and working (one line each).
Save the report incrementally. Finish with a short message: verdict, counts per severity, report path. No advice beyond findings and fixes for them.
```
