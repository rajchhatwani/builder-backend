# Session 0 — get the credentials ready (run this first)

Paste the block below into a new Claude Code session in /mnt/files/projects/builder-backend.

```
You are the environment-setup agent for the final end-to-end test of Backend Builder (backend + frontend + enterprise features). Do not change product code, do not commit or push.

Goal: tell me exactly which real accounts/credentials I must obtain so the final security and feature test sessions can test against REAL systems, and produce a ready-to-fill env file.

Steps:
1. Read: PLATFORM_SAAS_PLAN.md, .env.example, app/config.py (every BUILDER_* setting), docker-compose.yml, README.md, agent-orch/trigger_and_report_here.md, platform_implementation_agents/agent_3.md, agent_5.md, agent_6.md, agent_8.md, and review/review_PLATFORM_SAAS_PLAN.md §2 and §7 ("not run" items). Also skim app/services for every outbound integration (Stripe, SMTP, DNS TXT, SAML/OIDC IdP, SCIM, Keycloak, storage/S3/MinIO, payments, Redis, OpenTelemetry).
2. Never read, print or echo an existing .env, ~/.aws, ~/.ssh or *.pem. Never put a secret into any file you create other than the template below.
3. Create final_test/credentials/ with:
   - ENV_TEMPLATE.env — every setting needed, grouped by system, with comments: what it is, REQUIRED or OPTIONAL for the final test, test-mode vs live, and which test it unlocks. Values blank or clearly fake placeholders. Use test/sandbox mode everywhere; never ask for live-money keys.
   - GET_CREDENTIALS.md — for each external system, a short step-by-step for me: where to sign up (free tier / sandbox first), exactly what to click, what to copy into which variable, and what NOT to share. Cover at least: Stripe test mode (secret key, webhook secret via `stripe listen`, price ids for team/business, Customer Portal setup), SMTP (a sandbox inbox such as Mailpit/Mailtrap/Gmail app password), an SSO IdP for SAML and OIDC (Okta developer / Microsoft Entra / Google Workspace — pick the easiest free one, give both SAML and OIDC setup values to enter: ACS URL, entity id, redirect URI, cert), SCIM from that IdP (Okta/Entra provisioning app setup), a real DNS domain with TXT record control for domain verification (and what to put), Keycloak if needed, S3/MinIO storage, public URL/tunnel (ngrok/cloudflared) for webhooks and IdP callbacks, TOTP authenticator app, any second real e-mail inboxes/accounts needed for roles (owner, admin, member, outsider, platform admin, platform support).
   - TEST_ACCOUNTS.md — table of the user accounts/organizations/domains the test sessions will need, who creates each, and the exact name to use, so both test sessions agree.
   - READINESS_CHECK.md — a checklist I tick, plus a script final_test/credentials/check_env.py that loads the env file I fill (path given as argument), prints only PRESENT/MISSING/INVALID-FORMAT per variable (never the value), and does harmless live pings where possible (Stripe `GET /v1/balance` with the test key, SMTP login without sending, DNS lookup, IdP metadata URL fetch, DB connect). It must redact everything and exit non-zero if a REQUIRED item fails.
4. Tell me at the end, in a short list: the systems I must set up, rough time each takes, which ones are optional, and the exact command to run check_env.py.

Constraints: no new project dependencies (use the standard library / what is already installed). Keep everything under final_test/credentials/.
```
