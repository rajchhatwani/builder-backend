# Keycloak option: design and implementation plan

Status legend: `[ ]` todo, `[~]` in progress, `[x]` done. **Update this file as you work** so a new
chat can resume from it. Read also `PLAN.md` (builder architecture) and the memory notes
`keycloak-option-plan` and `generated-auth-design-decisions`.

## 1. Goal

A project can switch its identity provider from the built-in auth (own users, own tokens) to
**Keycloak**. The generated zip then contains a fully configured Keycloak (compose service +
realm import) or, for **shared** mode, only what is needed to trust an existing Keycloak realm.
Users get SSO, Google / Microsoft Entra ID / GitHub / generic OIDC login, MFA, brute-force protection
and an admin console, without configuring Keycloak by hand. Built for security / compliance audits:
secure defaults, no secrets in the zip, fail closed, auditable.

## 2. Decisions (agreed with the user, 2026-10-23)

1. **One provider per project**: `builtin` or `keycloak`, never both.
2. **Two modes** under `keycloak`:
   - `own`: the zip ships Keycloak (own Postgres, realm import, admin bootstrap).
   - `shared`: no Keycloak service; the API trusts an existing realm. A script registers this
     project's clients and roles in that realm (Keycloak admin partial import). Several generated
     projects can share one realm = one login across platforms.
3. **Roles are client roles** of the project's API client (not realm roles), so projects that share a
   realm cannot collide. Token claim: `resource_access.<api_client_id>.roles`.
4. v1 providers: Google (optionally restricted to a Workspace domain), Microsoft Entra ID
   (generated as OIDC against a **single tenant**), GitHub, generic OIDC. SAML / LDAP later.
5. Verification library: `cryptography` only (already approved for RS256), JWKS fetched with stdlib
   `urllib`. No Keycloak SDK, no PyJWT. Do not add other libraries without asking.
6. **Multi-tenancy** (added after v1) uses Keycloak Organizations: each organization is a tenant. Tenant id =
   uuid5(namespace of the realm, organization alias), so it is stable across environments. A user must be in
   exactly one organization (the default `organization` scope puts it in the token; a user in several gets no
   claim until the app asks for `organization:<alias>`); otherwise 403 `no_organization` /
   `organization_required`. Organizations are created and filled in Keycloak (no sign-up founder flow).
7. **Custom registration fields** (added after v1) are Keycloak declarative user-profile attributes (validators per
   type) delivered as access-token claims of the same name by attribute mappers on the browser clients, copied
   to nullable `auth_users` columns by the API. `unique` is rejected (Keycloak cannot enforce it); names that
   collide with Keycloak attributes or standard claims are rejected. Defaults apply only when a user is first
   seen; a claim that is absent leaves the stored value alone.
8. **Self-assignable roles are rejected** in Keycloak mode (deviation from the earlier chat, for
   security: mapping them to "default role for everyone" would silently grant the role). Roles are
   assigned in Keycloak. `is_default` roles become Keycloak default roles.
9. `invite_only` means: self-registration is off in the realm; admins create users in Keycloak.
   Builder invitations do not exist in Keycloak mode. `role.invite_only` is rejected.
10. Run mode: compose uses Keycloak **production mode** (`start`) with plain HTTP only behind a
    proxy (README explains TLS/proxy); the API refuses an `http://` issuer when `APP_ENV=production`.
11. The builder stores client IDs and tenant IDs, **never client secrets**. Secrets are env vars
    (`KC_IDP_<ALIAS>_CLIENT_SECRET`), substituted by Keycloak at import (`${VAR}` placeholders).
12. App URLs: explicit `redirect_uris` (no wildcards); web origins are derived from them.
    The generated realm also gets a `<web_client_id>-docs` client for Swagger UI (`/docs`).
13. **Turning Keycloak off** (see section 7): confirmation + impact report, Keycloak settings are kept
    (disabled, not deleted), blocked while other builder projects depend on this one, and the
    generated app locks to the provider it was first started with.

## 3. Spec (contract between builder and generator)

`app/core/spec_models.py`:

```text
SpecAuth.provider: "builtin" | "keycloak"          (default "builtin")
SpecAuth.keycloak: SpecKeycloak | None             (kept when provider is builtin so a switch back keeps settings)

SpecKeycloak
  mode: "own" | "shared"                           default "own"
  realm: str                                       [a-z0-9][a-z0-9-]{0,62}; default = project slug
  api_client_id: str                               default "<slug>-api"  (audience; no flows enabled)
  web_client_id: str                               default "<slug>-web"  (public, PKCE S256, code flow only)
  redirect_uris: list[str]                         exact URLs; https required except localhost / 127.0.0.1
  password_min_length: int                         12..128, default 12
  mfa: "off" | "optional" | "required"             default "optional"
  session_idle_minutes: int                        5..43200, default 30
  session_max_hours: int                           1..720,  default 10
  audit_retention_days: int                        7..3650, default 90   (login + admin events)
  identity_providers: list[SpecIdentityProvider]   max 10

SpecIdentityProvider
  alias: str       [a-z][a-z0-9-]{0,30}, unique
  type: "google" | "microsoft" | "github" | "oidc"
  display_name: str | None
  client_id: str                                   (secret = env KC_IDP_<ALIAS>_CLIENT_SECRET)
  tenant_id: str | None                            microsoft only, a GUID (no "common")
  hosted_domain: str | None                        google only, e.g. example.com
  issuer, authorization_url, token_url,           oidc only, https; userinfo_url optional
  jwks_url, userinfo_url: str | None               (Keycloak cannot read a discovery URL from a realm file)
```

Settings reused from existing `SpecAuth` fields in Keycloak mode: `email_verification_required`
(realm verifyEmail), `registration.invite_only` (registrationAllowed=false), `smtp` (realm SMTP;
user/password via env), `access_token_ttl_minutes` (realm accessTokenLifespan), `app_name`
(realm display name), `roles`, `permissions`, `security_headers_enabled`.

Ignored/forbidden in Keycloak mode: see validation rules below.

## 4. Builder side

### 4.1 Data model
- [ ] `app/core/enums.py` + `app/models/enums.py`: `AuthProvider`, `KeycloakMode`, `MfaMode`, `IdpType`.
- [ ] `project_auth_configs.provider` column (`builtin` default).
- [ ] New table `project_keycloak_configs` (1:1 with project, cascade delete): mode, realm, api_client_id,
      web_client_id, redirect_uris JSONB, password_min_length, mfa, session_idle_minutes,
      session_max_hours, audit_retention_days, identity_providers JSONB, `source_project_id` (nullable FK
      to projects, ON DELETE SET NULL; shared mode only, used for dependency tracking, not for the spec).
- [ ] Alembic migration for both.

### 4.2 API (`app/api/keycloak.py`, service `app/services/keycloak_service.py`)
- [ ] `GET    /projects/{id}/keycloak`           settings (404 if never configured)
- [ ] `PUT    /projects/{id}/keycloak`           create/replace settings (does not switch provider)
- [ ] `GET    /projects/{id}/keycloak/impact`    what enabling/disabling changes + dependents
- [ ] `POST   /projects/{id}/keycloak/enable`    body `{confirm: true}`; sets provider=keycloak
- [ ] `POST   /projects/{id}/keycloak/disable`   body `{confirm: true}`; sets provider=builtin; 409 listing
      dependent projects (those with `source_project_id` = this one and provider=keycloak)
- [ ] `PATCH /projects/{id}/auth` must NOT accept `provider` (only the two endpoints above change it).
- [ ] `spec_service`: export/import `auth.provider` + `auth.keycloak`; replacing a spec keeps the row.
- [ ] Never log or return secrets; there are none stored.

### 4.3 Validation (`app/core/validation.py`)
Applies when `auth.enabled` and `auth.provider == "keycloak"` (path prefix `auth.keycloak...`):
- [ ] `keycloak` block required; realm / client ids / alias patterns; unique aliases; max 10.
- [ ] `redirect_uris`: at least one for web client; https unless localhost/127.0.0.1; no `*`, no fragment,
      no userinfo, length caps.
- [ ] identity providers: required fields per type; Entra needs a GUID tenant; oidc needs https
      discovery URL; `hosted_domain` only for google; unknown combos rejected.
- [ ] numeric bounds as in section 3.
- [ ] rejected with a clear message: `multi_tenant`, custom registration fields, `sms_otp`,
      self-assignable roles, invite-only roles, `row_rule: tenant`.
- [ ] smtp required when `email_verification_required` (existing) or when a local-password login is
      possible; `app_url` is NOT required for Keycloak (no emailed links from the API).
- [ ] skip builtin-only checks (jwt algorithm, token store, rate limits, invitations, otp ttl).
- [ ] `AUTH_TABLES` depends on provider (`auth_users`, `auth_provider_lock` for keycloak).
- [ ] roles named `admin` still needed for `role_scoped`.

## 5. Generator side (generated project)

### 5.1 Files rendered when `provider == "keycloak"`
`app/core/generator/features/auth/` gets a keycloak branch in `module.py`
(`_KEYCLOAK_VERBATIM` / `_KEYCLOAK_RENDERED`); templates under `templates/keycloak/`:

- `app/auth/__init__.py`, `access.py` (same as builtin, verbatim reuse), `middleware.py` (reuse)
- `app/auth/config.py` : constants (realm, api client id, roles, role parents, default roles) +
  `AuthSettings` (env: `KEYCLOAK_PUBLIC_URL`, `KEYCLOAK_INTERNAL_URL` optional, `APP_ENV`,
  `AUTH_ALLOW_PROVIDER_SWITCH`).
- `app/auth/oidc.py` : JWKS cache + `verify_access_token` (see 5.2)
- `app/auth/models.py` : `AuthUser` (id = Keycloak `sub`, email, name, roles, is_active, deleted_at,
  created_at, updated_at; no password) and `AuthProviderLock`.
- `app/auth/service.py` : `effective_roles`, JIT user sync, provider lock check.
- `app/auth/deps.py` : `get_current_user` (bearer -> verify -> sync -> AuthUser), `CurrentUser`,
  `require_roles`.
- `app/auth/router.py` : `GET /auth/me`, `DELETE /auth/me` (anonymise local record), nothing else
  (no login / register / refresh endpoints exist).
- `alembic/versions/0002_auth.py` : `auth_users`, `auth_provider_lock`.
- `tests/_auth_support.py`, `tests/test_auth.py` (+ reuse `test_access.py`).
- docker module: `keycloak/realm.json` (own), `keycloak/partial-import.json` (always),
  `scripts/keycloak_register.py` (stdlib; registers clients + roles via admin partialImport),
  compose service(s), `.env.example`, `requirements.txt` (adds `cryptography`), README section.

The entity routers, `access_dependency`, row rules and `created_by_id` FKs keep working unchanged,
because `AuthUser.id` is the Keycloak `sub` (a UUID).

### 5.2 Token verification rules (generated `oidc.py`), fail closed
- Max token size 8 KiB; exactly 3 segments; base64url strict.
- Header: `alg` must be exactly `RS256` (reject `none`, HS*, anything else: stops algorithm confusion);
  `kid` required; ignore `jku`/`x5u`/`jwk` headers (never fetch keys from the token).
- Signature: RSASSA-PKCS1-v1_5 / SHA-256 with `cryptography`; keys from JWKS only (`kty=RSA`, `use`
  sig or absent, modulus >= 2048 bits).
- Claims: `iss` == configured issuer (exact), `aud` contains the API client id, `exp` required,
  `nbf`/`iat` checked with 30 s leeway, `sub` must be a UUID, `typ` claim must be `Bearer`
  (rejects ID and refresh tokens), `azp` optional.
- If `email_verification_required` and `email_verified` is false: 403 `email_not_verified`.
- JWKS: fetched from `<internal-or-public>/realms/<realm>/protocol/openid-connect/certs`, https
  verified, 3 s timeout, response capped at 64 KiB, cache 10 min; unknown `kid` triggers at most one
  refetch per 30 s (no DoS amplification); stale cache served for at most 1 h if Keycloak is down;
  otherwise 503 `auth_unavailable` (never accept unverified tokens).
- Errors return one generic 401 message; the reason goes to the structured log only (no token
  contents).
- Roles come from the token on every request (revocation latency = token lifetime, default 15 min,
  documented). DB role copy is updated only when it changes.
- `AuthUser.is_active=false` or `deleted_at` set = local kill switch, always 401.

### 5.3 Provider lock (prevents silent switching of identity source)
- Table `auth_provider_lock(id=1, provider, realm, created_at)` created by the auth migration of BOTH
  providers. On startup (lifespan) the app inserts the row if missing; if the stored provider/realm
  differs from the generated code it raises and refuses to boot unless `AUTH_ALLOW_PROVIDER_SWITCH=true`
  (then it updates the row and logs a warning). Documented in README.

### 5.4 Keycloak realm (`keycloak/realm.json`, own mode), hardening list
- realm name, display name, `enabled`, `sslRequired: "external"`, `registrationAllowed` from
  `invite_only`, `registrationEmailAsUsername: true`, `loginWithEmailAllowed: true`,
  `duplicateEmailsAllowed: false`, `verifyEmail` from spec, `resetPasswordAllowed` only with SMTP,
  `rememberMe: false`, `editUsernameAllowed: false`.
- `bruteForceProtected: true` (failureFactor 5, wait increments, permanent lockout off, quick-login
  check), `passwordPolicy`: `length(N) and notUsername and notEmail and passwordHistory(5)` and
  `hashAlgorithm(argon2)` if available else pbkdf2-sha512 default.
- Tokens: `accessTokenLifespan` from spec (seconds), `ssoSessionIdleTimeout`, `ssoSessionMaxLifespan`,
  `revokeRefreshToken: true`, `refreshTokenMaxReuse: 0`, `defaultSignatureAlgorithm: RS256`.
- Events: `eventsEnabled`, `eventsExpiration` (retention), `adminEventsEnabled`,
  `adminEventsDetailsEnabled`, listeners `jboss-logging` + `email` optional.
- Browser security headers: HSTS, `X-Frame-Options: SAMEORIGIN`, CSP `frame-src 'self'; frame-ancestors 'self'`.
- Clients:
  - `<api_client_id>`: confidential, no flows (`standardFlowEnabled/directAccessGrants/implicit/serviceAccounts`
    all false), holds the client roles.
  - `<web_client_id>`: public, `standardFlowEnabled` only, PKCE `S256` required, exact
    `redirectUris`, `webOrigins` derived, `post.logout.redirect.uris`, audience mapper adding the API
    client id to `aud`, roles mapper (client roles of the API client in `resource_access`).
  - `<slug>-docs`: public PKCE client for Swagger UI; redirect `${API_PUBLIC_URL}/docs/oauth2-redirect`.
- Roles: client roles from `auth.roles`; `is_default` roles are added to the realm default role.
- Identity providers from the spec, each with `${KC_IDP_<ALIAS>_CLIENT_SECRET}`, `trustEmail` only for
  Google/Entra (verified email), `syncMode: FORCE` for roles not needed, first-broker-login default
  flow, Google `hostedDomain`.
- Required action default: `CONFIGURE_TOTP` when `mfa == "required"`; OTP policy totp/HmacSHA1->HmacSHA256? (keep
  Keycloak default HmacSHA1 for authenticator-app compatibility, 6 digits, 30 s).
- SMTP: host/port/from/starttls from spec; `user`/`password` as `${SMTP_USERNAME}` / `${SMTP_PASSWORD}`.
- No default users, no default passwords; admin account comes from `KC_BOOTSTRAP_ADMIN_*` env (required).

### 5.5 Compose (own mode)
- `keycloak` service: pinned image tag (see `KEYCLOAK_IMAGE_TAG` constant in the docker module), command
  `start --import-realm --optimized=false`, env `KC_DB=postgres`, `KC_DB_URL`, `KC_HOSTNAME`
  (= `KEYCLOAK_PUBLIC_URL`), `KC_HTTP_ENABLED=true`, `KC_HEALTH_ENABLED=true`, `KC_PROXY_HEADERS`
  (env), `KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` (required), realm import volume read-only, management
  port 9000 **not** published, healthcheck on `/health/ready`, `restart: unless-stopped`.
- `keycloak_db`: its own Postgres with its own credentials (`KEYCLOAK_DB_PASSWORD` required), volume.
- `api` depends_on keycloak healthy (own mode); env `KEYCLOAK_PUBLIC_URL`, `KEYCLOAK_INTERNAL_URL=http://keycloak:8080`.
- Shared mode: no keycloak services; `KEYCLOAK_PUBLIC_URL` required.

## 6. Tests

Builder (`tests/`): validation (each rule above), service (enable/disable/impact/dependents/confirm),
spec round trip, generation golden for a keycloak project, API tests.
Generated project: forged tokens (alg none, HS256 with public key as secret, wrong kid, wrong iss,
wrong aud, expired, nbf in the future, ID token `typ`), JIT provisioning, role mapping, inactive user,
unknown role ignored, JWKS cache behaviour (refetch limit, stale), `email_not_verified`, access rules
via reused `test_access.py`, provider lock.
End to end (Docker): generate a keycloak project, `docker compose up`, create a user via the admin API,
obtain a token through the real web client (direct test client flow with PKCE), call the API, verify
role enforcement and that a token for another client / realm is refused. Also shared mode: second
project against the first project's Keycloak using `scripts/keycloak_register.py`.

## 7. Turning Keycloak off, explained

- Switching is explicit (`POST .../keycloak/disable` with `{confirm: true}`) and the response lists the
  impact: users live in Keycloak and are not migrated to built-in auth (passwords cannot be exported);
  deployed projects keep working until regenerated; after regenerating, the provider lock refuses to
  start the new build on the old database unless `AUTH_ALLOW_PROVIDER_SWITCH=true`; local profile rows
  (`auth_users`, keyed by Keycloak `sub`) stay, so data ownership survives switching back.
- Keycloak settings are retained (`provider` flips, the settings row stays) so enabling again restores them.
- If other builder projects point at this project's Keycloak (`source_project_id`), disabling returns
  409 with the dependent project names.

## 8. Dashboard (after the backend is done)

Separate **Identity provider (Keycloak)** page in the project sidebar (`frontend/src/components/Sidebar.tsx`
SECTIONS, route in `ProjectWorkspace.tsx`):
- [ ] toggle with confirmation dialog showing the impact report; own vs shared mode;
- [ ] realm / clients / redirect URIs; password, MFA and session settings; audit retention;
- [ ] identity-provider cards (Google, Entra, GitHub, OIDC) with per-provider help text and the exact
      redirect URL to paste into the provider console;
- [ ] checklist after download: env vars (`KEYCLOAK_*`, `KC_BOOTSTRAP_ADMIN_*`, `KC_IDP_*_CLIENT_SECRET`),
      how to start, first login, how to register a second platform (shared mode);
- [ ] hide / explain builtin-only settings in Authentication when provider is keycloak.
- [ ] `NextSteps.tsx` `requiredEnvVars` handles keycloak.

## 9. Phases and status

- [x] P0  this plan reviewed (user agreed 2026-10-23)
- [x] P1  builder: enums, models, migration `b3e1f7a92c64`, schemas, service, API, spec round trip
- [x] P2  builder: validation (`_check_auth_keycloak`) + tests (`tests/unit/test_keycloak_validation.py`, `tests/api/test_keycloak.py`)
- [x] P3  generator: keycloak auth branch (`auth/templates/keycloak/`, provider lock for both providers)
- [x] P4  generator: `features/keycloak/` (realm.json, clients.json, register script), compose, env, Makefile, README, requirements
- [x] P5  generated tests (`keycloak/tests/`), golden fixtures `keycloak_own` / `keycloak_shared`, `tests/unit/test_keycloak_generation.py`
- [x] P6  Docker end to end against a real Keycloak 26.8.1 (own + shared + MFA), see section 11; repeatable as `tests/e2e/test_keycloak_stack.py`
- [x] P7  dashboard: `frontend/src/components/KeycloakPanel.tsx` (+ sidebar entry, overview step, Keycloak-aware Authentication / Roles / Permissions / next-steps)
- [x] P8  README section, seed demos (`sso-hub`, `sso-portal`), Postman folder

## 10. Resume checklist for a new chat
1. Read this file and run `git status`; the checkboxes above say where we stopped.
2. Environment: Docker Desktop; frontend checks and test recipes are in memory (`dev-env-docker-workflow`).
3. Keep generated code stdlib + already approved libraries only; never put secrets in the zip.

## 11. What was verified against a real Keycloak (26.8.1, Docker)

Own mode (`keycloak_own` fixture, realm `hub`): realm import succeeds; `${ENV}` placeholders are
substituted (SMTP user, API url); healthcheck passes only on HTTP 200 of `/health/ready` (a 503 while
starting must not pass: the nested "Graceful Shutdown: UP" check is a false positive for a naive grep);
PKCE sign-in with the web client; API accepts the token, roles from `resource_access.hub-api`, default
roles added by the API; admin-only route 403 for a member; Swagger client token accepted; refresh/ID
tokens refused; password grant, implicit flow, unregistered redirect URI, missing PKCE all refused;
password policy rejects short passwords; brute-force lock-out after 5 failures; refresh token rotation
(reuse refused); all four IdP buttons appear on the login page; `/docs` OAuth wiring present.
Shared mode (`scripts/keycloak_register.py` against the realm of project 1): creates clients/roles and
scope mappings, re-run is idempotent; one user signs in to both projects; a token for one project's API
is refused by the other; each token carries only its own client's roles.
MFA required: realm import with the full required-actions list keeps all 14 standard actions and makes
CONFIGURE_TOTP the default action; sign-in stops at "configure authenticator".
**Gotchas found:** empty `KC_PROXY_HEADERS` is invalid (the line is documented, not set); importing a
realm that names any `requiredActions` replaces the whole list (so `_REQUIRED_ACTIONS` in
`features/keycloak/module.py` restates Keycloak's list for the pinned tag: re-check it on every tag bump);
Keycloak marks its cookies `Secure` even on http://localhost (browsers accept this, `httpx` needs manual
cookie handling in scripts).
The same checks are now automated in `tests/e2e/test_keycloak_stack.py` (own + shared, ~3 minutes, needs Docker).
Mutation check done by hand: weakening any of audience / issuer / token type / expiry / algorithm pin /
signature / realm-role trust / email-verified / unknown-role / inactive-user checks in the generated
`oidc.py`, `deps.py` or `service.py` makes the generated tests fail (10 of 10).
MFA "required" and the Keycloak container hardening (`cap_drop: ALL`, `no-new-privileges`) were checked by hand only.

## 12. Next steps (beyond the checklist)
- Add the MFA-required check to `tests/e2e/test_keycloak_stack.py` (done by hand only).
Everything from the first list is done. Remaining ideas, none required:
- A tenant founder flow (create an organization at sign-up). Keycloak has no self-service for it; it would
  need the API to call the admin API with a service account.
- Per-organization roles (roles are realm-wide per client today).
- Keycloak Organizations invitations surfaced in the dashboard.
- Bump the pinned Keycloak tag: re-check `_REQUIRED_ACTIONS` and `_DEFAULT_USER_PROFILE` in
  `features/keycloak/module.py` against a fresh realm first (both are restated because importing them replaces
  Keycloak's own list).

## 13. Added after the first release

- **Default roles** are Keycloak realm default roles in own mode (`default-roles-<realm>` composite, merged with
  Keycloak's own defaults, verified). The API still unions `DEFAULT_ROLES`, and shared mode leaves the realm
  defaults alone so other platforms are not affected.
- **MFA required** and the container hardening are now automated (`test_required_mfa_*`,
  `test_the_keycloak_container_is_locked_down`).
- **OIDC discovery fill** in the dashboard reads `.well-known/openid-configuration` in the browser (needs the
  provider to allow cross-origin reads; otherwise it says so and the fields are typed by hand).
- **Custom fields and tenants**: generator (`auth/templates/keycloak/`, `features/keycloak/module.py`), the
  register script (merges profile attributes, turns Organizations on, gives the browser clients the
  `organization` scope), fixture `keycloak_tenant`, tests in `tests/unit/test_keycloak_*`,
  `tests/e2e/test_keycloak_stack.py` (real realm: attributes validated, registration page, claims typed,
  organizations as tenants, isolation, no/several organizations), mutation checks (14 of 14 caught; one
  mutant of the several-organizations check is equivalent because the guard sits in `deps.py`).
- **Real Keycloak behaviour worth knowing**: with Organizations enabled the login is two steps (user name, then
  password); the `organization` claim is a list of aliases; a user in several organizations gets no claim by
  default; custom attribute claims of type double may arrive as strings (the API coerces).
