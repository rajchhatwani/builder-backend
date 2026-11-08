# SOC 2 Type I - evidence preparation

Status: **preparation only.** No audit has been engaged, no control is claimed as operating, and
nothing in this file is evidence. It maps the Trust Services Criteria that `PLATFORM_SAAS_PLAN.md`
§11 names to where the control lives in this repository, the artefact to collect, and what is still
missing. Fill the "Owner" and "Collected" columns as evidence is gathered. A Type I report
describes the *design* of controls at a point in time; a Type II adds operating effectiveness over a
period and needs this evidence collected on a schedule.

## 1. System description inputs

- Architecture and isolation model: `docs/MULTITENANT_ARCHITECTURE.md`.
- Customer-facing setup: `docs/SSO_SETUP.md`, `docs/SCIM_SETUP.md`.
- Data classification: customer project specs (confidential); credentials and secrets (restricted,
  encrypted); account data (e-mail, name, last sign-in; personal data); audit log (internal).
- Sub-processors to list: hosting/database provider, Stripe (billing), outbound e-mail provider.

## 2. Control map

| Criterion | Control as designed | Where in the code / docs | Evidence to collect | Gap | Owner | Collected |
|---|---|---|---|---|---|---|
| CC6.1 Logical access | Per-request authentication, org membership and role checks; default-deny route tables; RLS as a second wall | `app/api/security.py`, `platform_authz.py`, `app/core/rls.py`; tests `test_access_matrix.py`, `test_org_invariants.py`, `test_rls.py` | CI run of the test suite for the audited commit; RLS `status` output from production; list of DB roles (none with `BYPASSRLS` except ops) | RLS not yet enabled in production (owner decision pending) | | |
| CC6.1 Authentication | Scrypt passwords, TOTP (mandatory for staff, optional/required per org), SSO, session rotation, rate limiting, lockout | `platform_auth_service.py`, `mfa_service.py`, `core/totp.py` | Config export (`admin_mfa_required`, lockout, TTLs); list of staff with MFA enrolled | WebAuthn/passkeys not built | | |
| CC6.2/6.3 Provisioning and removal | Invitations, SCIM provisioning/offboarding (signs out everywhere), org member removal, account suspension | `organization_service.py`, `scim_service.py` | Sample offboarding with audit rows; quarterly access review of staff accounts and platform admins | No scheduled access-review job; SCIM not yet validated against real IdPs | | |
| CC6.6 Boundaries | HTTPS/HSTS, CORS allow-list, CSRF header on cookie endpoints, request-size cap, input guard (NUL), SSRF guard on IdP URLs | `app/main.py`, `input_guard.py`, `sso_service.py` | WAF / load-balancer config; TLS scan; pen-test report | Pen test not performed (`PENTEST_PLAN.md`) | | |
| CC6.7 Data in transit/at rest | TLS; secrets encrypted with an application key; hashes for tokens | `core/crypto.py` | KMS/key-management description; DB encryption-at-rest setting of the provider | No per-org keys; key-rotation procedure not written | | |
| CC6.8 / CC8 Change management | Alembic migrations, test-first changes, code review | repo history, `alembic/versions/` | PR/review records, CI results, migration log | Branch protection and required reviews to confirm | | |
| CC7.1 Detection | Denied-by-quota / failed login insights; `access.denied` audit | `/admin/insights`, `audit_service.py` | Alert rules and a sample alert | No alerting pipeline defined | | |
| CC7.2 Monitoring | Structured logs with `organization_id`/`request_id`; append-only audit log (DB trigger) | `app/core/observability.py`, migration with the trigger | Log retention config; trigger definition; sample immutable-log test | Log shipping and retention to confirm | | |
| CC7.3/7.4 Incident response | Impersonation and operator actions audited; operator SCIM rotation | `impersonation_service.py` | Incident-response policy; drill record | **No written IR policy**; the digest job exists but needs a scheduler entry and a destination in each environment | | |
| A1 Availability | Postgres backups; per-org export | `GET /orgs/{slug}/export`, ops runbooks | Backup schedule, restore-test record, RPO/RTO | Backup/restore test and DR runbook not in repo | | |
| C1 Confidentiality | §7.1 operator blind spots; encrypted secrets; export excludes secrets | `tests/api/test_operator_secrets.py`, `test_org_export.py`, review `test_adv_secrets.py` | Test output for the audited commit | - | | |
| PI1 Processing integrity | Quotas and seat accounting with locking; Stripe webhook signature, idempotency and ordering; tenant-scoped export | `organization_service.py`, `stripe_webhook_service.py` | Reconciliation job output | Reconciliation has no scheduler | | |
| P (Privacy) | Minimal data; erasure via org deletion (grace period); SCIM deactivation; operators see no spec content | `org_deletion_service.py`, `docs/MULTITENANT_ARCHITECTURE.md` §4–6 | DPA, privacy notice, deletion request sample | Erasure from backups follows retention; no DSAR runbook | | |
| Impersonation (CC6.1/6.3) | Per-org consent, admin-only permission, 10-minute token, read-only default, full audit | `impersonation_service.py`; tests `test_impersonation.py` | Policy toggle screenshot; audit sample; list of sessions per quarter (`GET /admin/impersonation/sessions`) | Schedule the digest job (`python -m app.jobs.impersonation_digest`) and keep its output as evidence | | |

## 3. Collection routine

| When | What | How |
|---|---|---|
| Each release | Full test suite result, `ruff`, `mypy`, frontend build | CI artefacts, attached to the release |
| Monthly | Staff accounts, roles and MFA status | `/admin/users`; export dated |
| Monthly | Impersonation sessions and their reasons | `/admin/impersonation/sessions` export, reviewed and signed |
| Quarterly | Access review (staff, DB roles, cloud IAM); RLS `status`; dependency/vulnerability scan | Checklist + screenshots |
| Yearly | Pen test and retest; DR/restore test; policy review | Reports, `PENTEST_PLAN.md` |

Never put customer data or secrets in the evidence folder; use the seeded canary tenants.

## 4. Policies still to write (none exist in this repository)

Information security, access control, change management, incident response, vendor management,
business continuity/DR, data retention and deletion, acceptable use, and an employee security
awareness record. The controls above are *designed*; auditors will also want these documents and
proof that people follow them.

## 5. Before engaging an auditor

1. Decide Type I scope (which criteria; Security is mandatory).
2. Pick a readiness tool or advisor; agree the system boundary.
3. Close the "Gap" column items that are cheap (alerting, restore test, IR policy).
4. Take a baseline snapshot of every artefact above, dated.
