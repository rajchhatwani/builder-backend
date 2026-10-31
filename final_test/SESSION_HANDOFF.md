# Session handoff: read this FIRST (sessions 1 = security, 2 = features)

Everything below was set up and verified on 2026-10-29. **You do not need the user for anything.** If something here
turns out not to work, record it in your report as "could not test: <reason>" and continue; do not stop to ask.
Never print, log or write any password, token, TOTP secret, recovery code, SCIM bearer, cookie or invite link
(use `[REDACTED]`). Do not change product code (`app/`, `alembic/`, `frontend/src/`, `tests/`). No commits.

## 0. Run order and isolation
Run **session 1 (security) first, then session 2 (features)**, never both at once: they share one ngrok domain
(`https://cinderous-overfamiliar-sanford.ngrok-free.dev`), one Okta tenant, one Stripe test account and one mailbox.
Start every session with a clean, configured database:

```
cd /mnt/files/projects/builder-backend
final_test/harness/stack.sh restore configured      # DB = SSO(OIDC) active + verified domain + SCIM enabled + staff + bb-owner
final_test/harness/stack.sh up production            # Postgres, migrations, frontend build, proxy, API, ngrok tunnel
final_test/harness/stack.sh status                   # all five lines must say 200 / accepting connections
```
Other commands: `down`, `down --all`, `logs api|ngrok`, `snapshot NAME` (take one before a destructive test),
`restore NAME`. `up local` starts a second, local-mode stack (use other ports/DB, see below). The first line of
`stack.sh` documents every variable (`API_PORT`, `PROXY_PORT`, `PG_PORT`, `DB_NAME`, `MAIL=sink`, `STACK_SET`).

**Gotchas that already cost time:**
- Never run `pkill -f` / `pgrep -f` with a pattern that also appears in your own command line: it kills your shell
  (exit 144). `stack.sh` handles process cleanup itself.
- Your Bash tool times out at 120 s: run long jobs with `run_in_background` and write logs to a file; use `python3 -u`
  (unbuffered) or the output stays empty until the end.
- Public URL = one origin for app + API (`https://cinderous-overfamiliar-sanford.ngrok-free.dev`). Browser requests to
  ngrok's free domain get an interstitial unless they carry the header `ngrok-skip-browser-warning: 1`; send it **only to
  the ngrok host** (it breaks CORS on other origins, e.g. Okta). `curl` needs `-H 'ngrok-skip-browser-warning: 1'`.
- `docker` works; images pull from the internet. Chrome: `/usr/bin/google-chrome-stable` (headless). Node + puppeteer-core
  are pre-installed in `~/bb_tools` (import from `/home/require1/bb_tools/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js`).
- **TOTP replay protection (a feature):** the same 6-digit code is refused twice within one 30-second step, so two staff logins
  for the same account in the same window fail with 401. `bb.Api.login` waits for the next step and retries once; do the same in your own scripts.
- The environment file is `~/final_test.env` (permissions 600). Load it with `final_test/credentials/with_env.py` or the
  helper library below. It is outside git. Do not copy it into the repo, and do not print it.

## 1. What is already configured (in the `configured` snapshot)
| Item | State |
|---|---|
| Platform admin | `raj@dumbpotato.com` (password `BUILDER_BOOTSTRAP_ADMIN_PASSWORD`, TOTP secret `FINAL_TEST_PLATFORM_ADMIN_TOTP_SECRET`) |
| Platform support | `bb-support@dumbpotato.com` (password `FINAL_TEST_PASSWORD`, TOTP `FINAL_TEST_PLATFORM_SUPPORT_TOTP_SECRET`) |
| Org `bb-sso` ("BB SSO"), plan enterprise | owner `bb-owner@dumbpotato.com` (password `FINAL_TEST_PASSWORD`); SSO **OIDC active**, JIT on, "trust unverified e-mail" ON (Okta sends no `email_verified`); verified domain `dumbpotato.com`; SCIM enabled, group map `bb-test-admins`→admin |
| Accounts that exist | `bb-owner`, `bb-sso1` (JIT member), `bb-sso2` (SCIM-created, then deactivated) |
| Not created yet (your journeys create them) | `bb_individual`, `bb_admin`, `bb_member`, `bb_outsider`, `bb_owner2` @dumbpotato.com (names in `final_test/credentials/TEST_ACCOUNTS.md`; underscores because GoDaddy mailboxes allow no hyphen) |
| Orgs you create | `bb-acme`, `bb-other`, `bb-delete` as in TEST_ACCOUNTS.md (SSO/SCIM work only in `bb-sso`, the only org with a verified domain) |

Customer password for every test account = `FINAL_TEST_PASSWORD`. **Warning:** an SSO sign-in by an existing
password account wipes that account's password (anti pre-hijack feature). Don't SSO-sign-in with accounts you still
need; restore with `python3 final_test/credentials/set_test_password.py ~/final_test.env <email>`.

## 2. Tools you can use (all under `final_test/`, all redact)
| Tool | What it does |
|---|---|
| `harness/bb.py` (import it) | `Api()`: `.customer("owner"/"admin"/"member"/"outsider"/"individual")` (signs up if missing), `.staff("admin"/"support")` (password + generated TOTP), `.call(method, path, body, token)`; `wait_mail(to, subject, timeout)` reads the real GoDaddy inbox over IMAP (INBOX **and Spam**) or Mailpit with `MAIL=sink`; `totp(secret)`; `Scim(base, token)` to act as an IdP; `stripe_webhook(type, obj, ...)` posts a correctly SIGNED Stripe event (tamper with args for forgery/replay/out-of-order tests). CLI: `python3 harness/bb.py roles|totp admin|mail --to X --subject Y` |
| `harness/okta_login.mjs` | Headless Chrome SSO sign-in through the app's e-mail-first page and the real Okta page. Handles Okta's "choose Password" step and a forced password change. See section 4 for its current limit |
| `harness/probe.mjs` | Dumps a page's inputs/buttons (to build UI scripts quickly) |
| `credentials/check_env.py ~/final_test.env` | Readiness (PRESENT/MISSING per variable, live pings) |
| `credentials/verify_totp.py`, `set_test_password.py`, `with_env.py` | TOTP proof, password restore through the operator console, run-with-env |
| `credentials/NOTES_FOR_TEST_SESSIONS.md` | Observations already made during setup (items 1-9): re-verify each, they are candidate findings |

## 3. Real systems and how hard you may hit them
- **Okta (real tenant `integrator-3709310`)**: SAML app `BB Test SAML`, OIDC app `BB Test OIDC`, SCIM app `BB Test SCIM`;
  users `bb-sso1`, `bb-sso2`, `bb-foreign@other-example.test`, `bb-owner`. Keep to a few dozen sign-ins total (Okta rate limits).
  The org currently uses **OIDC**; saving SAML in the SSO form replaces it (one protocol per org). Okta details for
  the SAML form are in `GET_CREDENTIALS.md` §6 (issuer/SSO URL/certificate are in `~/final_test.env` and the cert file).
- **Stripe test mode** (`sk_test_`; prices team/business, Customer Portal configured with plan switching): use Checkout
  with test cards (`4242 4242 4242 4242`; decline `4000 0000 0000 0341`/`9995`). **No webhook endpoint is registered at
  Stripe** (registering one would change the user's Stripe account; do not do it). For webhook tests use `bb.stripe_webhook(...)`
  (signed with the env secret, same format as Stripe) and, if it works for you, the CLI: `~/.stripe/bin/stripe listen
  --forward-to http://127.0.0.1:8000/billing/stripe/webhook`, then `stripe trigger ...`. If the CLI's secret differs from the
  env's, restart the stack with `STACK_SET="BUILDER_STRIPE_WEBHOOK_SECRET=<cli-secret>"` (do not write it to files).
- **Mail**: the real mailbox `raj@dumbpotato.com` (aliases `bb_*@`). GoDaddy rate-limits and files the app's mail under
  **Spam** (the app sends no `Date`/`Message-ID`: report it). Send **at most ~25 real mails in total**; for bulk runs use
  `MAIL=sink final_test/harness/stack.sh up production`; mail goes to Mailpit (read it with `wait_mail` or `http://127.0.0.1:8025`).
- **DNS** is at Vercel and you cannot edit it: `dumbpotato.com` is already verified for `bb-sso`. Test the failure paths (an unverified
  domain, a wrong TXT, a domain claimed by two orgs) but do not expect to verify a second domain; mark that "not testable".
- **Keycloak/MinIO/Redis/OTLP** (optional generator features): `docker run` them as needed; defaults are in the env file.

## 4. What is NOT automated (and what to do instead; do not ask the user)
1. **Okta password for the test users.** `bb-sso1`'s Okta password was changed by the user at first sign-in and the env value
   `FINAL_TEST_IDP_USER_PASSWORD` is stale: `okta_login.mjs` reaches Okta's password page and Okta answers "Unable to sign in". Try it
   first (`node harness/okta_login.mjs <app-url> <email> <password> [<new-password>]`); if it fails, treat real-Okta
   browser logins as **blocked**, record it, and use the fallbacks:
   - **Synthetic SAML IdP:** generate your own key and certificate (`openssl`), sign SAML responses with `signxml` (a project dependency, use `uv run`), put your certificate in the org's SAML form, and drive the ACS endpoint yourself. This covers signature, audience, recipient, replay, wrong cert, XXE/wrapping, expired, `InResponseTo`, JIT, domain rules, in full.
   - **Synthetic OIDC IdP:** run Keycloak (`docker run quay.io/keycloak/keycloak:26.0 start-dev`) with `STACK_SET="BUILDER_SSO_ALLOW_HTTP_IDP=true BUILDER_SSO_ALLOW_PRIVATE_IDP=true"` (itself a test of the SSRF switch).
   - **SCIM** needs no Okta: act as the IdP with `bb.Scim(...)` (rotate the token in the org's SCIM section or via the API, as the owner).
2. **Stripe webhook registration at Stripe**: see section 3.
3. **A phone authenticator**: not needed, use `bb.totp(secret)` and capture the base32 secret shown at enrolment.
4. **Adding DNS records**: not possible, see section 3.

## 5. Reports, evidence, cleanliness
Write only where your prompt says (`final_test/security/` or `final_test/features/`). The harness writes logs to
`final_test/logs/` and `final_test/run/` and snapshots to `~/bb_snapshots/` (outside the repo). Redact before saving
anything. Take a snapshot before every destructive test (`stack.sh snapshot before_x`) and restore afterwards.
When you finish: `final_test/harness/stack.sh down` (leave Postgres), then give the short final message your prompt asks for.
