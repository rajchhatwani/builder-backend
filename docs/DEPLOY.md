# Deploying the platform (beta / production)

Stack (`docker-compose.prod.yml`): Postgres, API, scheduler, dashboard + Caddy (automatic HTTPS), and Keycloak
with its own Postgres. Images are built by GitHub Actions, pushed to GitHub Container Registry (`ghcr.io`), and
pulled by your server. Secrets live only in `/opt/builder/.env` on the server.

## One-time server setup
1. A Linux server with Docker + Docker Compose v2, ports 80/443 open, and two DNS names pointing at it:
   the app (`BB_DOMAIN`) and Keycloak (`KC_DOMAIN`).
2. A deploy user in the `docker` group, and an SSH key pair for the workflow (public key in `authorized_keys`).
3. `mkdir -p /opt/builder && cd /opt/builder`, then:
   - copy `.env.example` to `.env`, fill it in (`openssl rand -hex 32` for each secret), `chmod 600 .env`
   - `printf 'k1 %s\n' "$(openssl rand -base64 32)" > keys.txt && chmod 600 keys.txt`
     (data-at-rest key file; back it up, losing it loses stored credentials)
4. GitHub: create environments `beta` (and `production`, with required reviewers). In each set
   variables `BB_DOMAIN`, `DEPLOY_HOST`, `DEPLOY_USER`, optional `DEPLOY_PATH`, and secrets `DEPLOY_SSH_KEY`
   and `DEPLOY_KNOWN_HOSTS` (`ssh-keyscan -H <host>`).
5. First admin: set `BB_BOOTSTRAP_ADMIN_EMAIL` / `BB_BOOTSTRAP_ADMIN_PASSWORD` in `.env` for the first start,
   or run `docker compose exec api /app/.venv/bin/python /app/scripts/create_admin.py you@example.com`.

## Releasing
- Push to `beta` -> CI -> build/push images -> deploy to the `beta` environment.
- Tag `v1.2.3` (or run the workflow manually) -> `production`.
- The server runs `deploy.sh <tag>`: pull, start databases, **migrate as the owner role**, (re)create the
  least-privilege `builder_app` role, start everything, check `https://$BB_DOMAIN/health`.
- Roll back: on the server `./deploy.sh $(cat .previous-tag)` (database migrations are not reversed).
- Images are tagged `sha-<12 chars>` and `latest`. Dependabot keeps actions and dependencies current.

## Keycloak (instead of Okta)
Keycloak runs at `https://$KC_DOMAIN`. First sign in with `KC_ADMIN_USER` / `KC_ADMIN_PASSWORD`, then:
1. Create a realm (e.g. `builder`). Create a **client** (OpenID Connect, confidential, standard flow) with
   redirect URI = the callback shown in the platform's org SSO tab. Copy the client secret.
2. In the platform: Organization -> Single sign-on -> OpenID Connect. Issuer =
   `https://$KC_DOMAIN/realms/builder`, then the client id and secret.
3. Sign in with Google: in the realm, Identity providers -> Google, with an OAuth client created in Google Cloud
   (authorised redirect URI = the one Keycloak shows). Users then pick Google on the Keycloak login page.
4. SCIM provisioning is not built into Keycloak; plain SSO login does not need it.

## Previews and the agent sandbox (optional, on the same server)
Previews and the builder agent's draft workspaces run generated code in gVisor-isolated containers started by a
**narrow runner** (the only thing with `docker.sock`). Turn it on with `SANDBOX_ENABLED=true`; the workflow then also
builds `builder-runner` and `builder-preview-app`, and `deploy.sh` adds `docker-compose.sandbox.yml`.

What that overlay changes: the API, scheduler, runner and proxy run on the **host network** (the API reaches sandbox
containers by their internal-network IPs). They still listen on `127.0.0.1` only, except Caddy on 80/443; the Postgres
and Keycloak ports are published on `127.0.0.1` only.

Do once on the server, as root, before the first sandbox deploy:
1. **gVisor:** install `runsc` and register it: `runsc install && systemctl restart docker`; check
   `docker info | grep runsc`. (`BB_SANDBOX_RUNTIME=runc` is a weaker choice and is refused outside local/test.)
2. **Address pools:** make sure Docker's default pools never hand out `172.30.0.0/16` (or set `SANDBOX_SUBNET_POOL`).
3. **Firewall:** `sudo bash /opt/builder/scripts/sandbox_firewall.sh apply --yes`. It stops containers reaching the cloud
   metadata address, the host gateway and private ranges. It needs the `bb-` sandbox network labels the runner creates.
4. **Data directory:** `sudo mkdir -p /var/lib/builder` (path = `BB_DATA`; it must be the same on host and in containers).
5. **.env:** `SANDBOX_ENABLED=true`, `PREVIEW_DOMAIN` (a third DNS name, different from the app's: the Workbench needs a
   separate origin), `BB_RUNNER_TOKEN=$(openssl rand -hex 32)`; set the `PREVIEW_DOMAIN` repository variable too (it is
   baked into the dashboard build), and the `SANDBOX_ENABLED` variable (`true`) for the workflow.
6. Check from the repo (needs the same BUILDER_* environment): `scripts/golive_check.sh`, and `scripts/sandbox_hostile_check.sh`
   for the container escape tests.

Known limits: the runner holds `docker.sock` as root inside its container (token-checked, loopback only); preview databases use
the Postgres owner role; the preview image carries a curated dependency set (extend `docker/preview-app/requirements.txt`).
