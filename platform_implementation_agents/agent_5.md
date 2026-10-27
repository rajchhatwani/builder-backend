# Agent 5 report — claude-opus-5-5 — 2026-10-26 → 2026-10-27 (complete)

## Scope accepted
Row 5: the two Round 2 P2 gaps, then Phase D.1–D.4 (SSO backend). The owner told me to make the
open decisions myself; they are listed under "Decisions".

Baseline before changes: `tests/api tests/unit` → 1751 passed, 2 skipped.

## Implementation summary
### Round 2 gaps (done)
- `app/api/security.py`: the 423 `org_deletion_pending` details now carry `organization_id`,
  `organization_slug`, `organization_name` and `deletion_scheduled_for`.
- `GET /projects`: `ProjectRead.organization_locked` plus `organization_deletion_scheduled_for`.
  Projects of locked orgs stay listed, but flagged.
- Frontend: `OrgLockedPrompt` uses the org named in the 423 (it falls back to `GET /orgs` only
  for an older backend). `ProjectsPage.tsx` reads `project.organization_locked` and calls
  `GET /orgs` only when a project is flagged, because the locked card still needs the org's name and
  slug, which `ProjectRead` doesn't carry.

### Phase D.1–D.4 (backend done)
- Migration `e4b9c2d7a1f5`, the new **Alembic head**: `sso_connections` and `sso_domains` as in §3.1,
  plus `jit_enabled`/`jit_role` (D.4 "allowed roles for JIT"), timestamps, and the new table
  `sso_login_requests`, which holds the one-time login state. Models are in `app/models/sso.py`.
- `app/services/saml.py`: AuthnRequest (Redirect binding), SP metadata, and Response validation.
  `signxml` checks the signature, and every value is read from the signed subtree. It also checks
  issuer, audience, recipient, time windows and InResponseTo. It refuses DTDs, unsigned input,
  encrypted assertions and IdP-initiated logins.
- `app/services/oidc.py`: discovery, PKCE S256, nonce, code exchange (client_secret_basic, else
  _post), and ID tokens verified against the JWKS with asymmetric algorithms only. An SSRF guard
  covers every outbound URL.
- `app/services/dns_txt.py`: TXT lookup at `_builder-verification.<domain>`, value
  `builder-verification=<token>`.
- `app/services/sso_service.py`: config, domains, activation, discovery, login start and
  finish, and JIT. `allow_sso` is gated through `OrganizationService._deny` (402
  `sso_not_in_plan`, reason `feature`).
- `app/api/sso.py`: public routes `/sso/metadata/{slug}`, `/sso/{slug}/login`,
  `/sso/saml/{slug}/acs` and `/sso/oidc/{slug}/callback`; org-admin routes `/orgs/{slug}/sso…`, which
  are listed in `ORG_ROUTE_ROLES` and need a session (API tokens are refused).
  `POST /account/login/discover`. All public routes are in `PUBLIC` in the access matrix.
- Settings: `BUILDER_PUBLIC_API_URL`, `BUILDER_SSO_ALLOW_PRIVATE_IDP`, `BUILDER_SSO_ALLOW_HTTP_IDP`,
  `BUILDER_SSO_LOGIN_TTL_SECONDS`, all documented in `.env.example`.
- `pyproject.toml`: a mypy override for `lxml.*`, which has no stubs, like the one for reportlab.
- Frontend types: `Project.organization_locked` and `organization_deletion_scheduled_for`; the
  org fields on `OrgLockedDetail`; `QuotaDetail.resource` 'sso' and `reason` 'feature' (402
  `sso_not_in_plan`). `QuotaPrompt` labels it "single sign-on".
- After sign-in the browser is redirected to `#/sso/complete` with the refresh cookie set; on
  failure it goes to `#/login?sso_error=<reason>`.

## Decisions (made for the owner)
- **New dependencies:** `signxml` (brings `lxml`), `dnspython`, and `pyjwt` (already present
  through `mcp`, now declared directly).
- An SSO login is accepted only for e-mails on a domain that org has verified. Platform staff
  can't sign in through a customer's SSO. Suspended accounts are refused.
- A login state is single-use, expires after 10 minutes, and is bound to the browser with the
  `bb_sso` cookie (Secure, SameSite=None, path `/sso`).
- Domains: per-org deterministic tokens. An unverified claim moves to whichever org claims it
  next; a verified one is final (409). Free-mail domains are refused.
- JIT: on by default, role member or admin (never owner), seat-checked, adds an existing
  account to the org, and gives new accounts a personal org. SSO-only accounts have no password.
- A downgraded or locked org: discovery falls back to the password form, and login is refused.

## Tests I wrote (TDD; red first, mutation-checked)
- `tests/unit/test_saml.py` (23) and `tests/unit/test_oidc.py` (27).
- `tests/api/test_sso_config.py` and `tests/api/test_sso_login.py` (41), plus
  `tests/api/test_org_locked_details.py` (4) and a new SSO migration test.
- Mutations caught: no signature check, no verified-domain check, no browser binding, no
  single-use check, staff allowed.
- `tests/sso_fake_idp.py`: a test IdP that signs with a self-signed cert.

## Test run result
```
tests/api tests/unit  →  1847 passed, 2 skipped, 60 warnings in 218.63s
(baseline 1751 + 96 new; skips and the Starlette 422 deprecation warnings are pre-existing)
```
- Frontend: `npx tsc -b` clean; `npm run lint` 57 warnings, the same count as before, none from
  my changes; `npx vite build` OK.
- ruff is clean on every file I touched; the 10 findings left in `app/` are pre-existing and in
  files I didn't touch.
- mypy is clean on the SSO modules; the 2 errors it reports are pre-existing
  (`stripe_client.py:86`, `security.py:274`).
- E2E not run (needs Docker Compose).

## Open items / known issues
- Not checked against a real IdP (Okta, Entra ID, Google). The first deploy should test one.
- Row 6 also needs: login-page discovery UI, a `#/sso/complete` route, and showing `sso_error`.

## Improvement scope — out of current phase
- An "enforce SSO" policy (refuse password login for the domain) is not in the plan.
- IdP metadata import, signed AuthnRequests, encrypted assertions, and a JWKS cache.
- The DNS-rebinding gap: the SSRF guard resolves the host before httpx resolves it again.

## HANDOFF: continue at row 6 — SSO UI + MFA + session TTL (Phase D.5–D.7, §4.4, §8)

What's ready for row 6:
- **Customer SSO page** (`#/org/<slug>/sso`): everything is under `GET|PUT|DELETE /orgs/{slug}/sso`,
  `POST …/sso/activate|deactivate`, `POST …/sso/domains`, `POST …/sso/domains/{domain}/verify` and
  `DELETE …/sso/domains/{domain}`. GET returns `sp` (entity ID, ACS, metadata URL, OIDC redirect
  URI, login URL), `domains[]` with the TXT record name and value, `allowed_by_plan`,
  `idp_certificate` (fingerprint only) and `oidc_client_secret_set`. Saving needs a session (API
  tokens get 403 `session_required`). Error codes: `sso_not_in_plan` (402),
  `sso_not_for_personal_orgs`, `sso_not_configured`, `no_verified_domain`, `domain_taken`,
  `domain_not_verified` (409, with the record to add), `last_verified_domain`,
  `invalid_certificate`, `insecure_url` and `oidc_client_secret_required` (422).
- **Login page** (missing today): call `POST /account/login/discover {email}`. For
  `{method:"sso", login_url}`, set `window.location = login_url`; otherwise show the password
  field. Add a `#/sso/complete` route that calls `/account/refresh` and goes home, and show
  `#/login?sso_error=<reason>`. The reasons are the codes in `sso_service` / `saml` / `oidc`, e.g.
  `email_domain_not_verified`, `not_provisioned`, `seat_limit`, `sso_unavailable`, `bad_signature`.
- **"Test with my own email" (D.6) and the operator test button (D.5)**: not built. The simplest
  version is a `test` flag on `GET /sso/{slug}/login` that skips JIT and reports the result.
  `SsoService.start_login`/`_sign_in` are the places to add it, and `sso_login_requests` would
  need a column for the flag.
- **Operator SSO status column (D.5)**: add `sso_protocol` / `sso_active` / verified-domain count
  to `AdminOrgRead` from `sso_connections` / `sso_domains`.
- **MFA (§4.4)**: SSO users have no password (`password_hash = "!sso-only"`). A per-org "require
  MFA" policy should treat an SSO login as the IdP's job, or row 6 must decide otherwise. Note it.
- `.env.example` documents `BUILDER_PUBLIC_API_URL`, which must be what the IdP can reach.
