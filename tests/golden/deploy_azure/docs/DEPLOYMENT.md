# Deploying Notes to Azure

Generated from the project spec. Everything here is code you can read and change: GitHub Actions workflows
in `.github/workflows/` and Terraform in `deploy/azure/`. **No cloud credential is stored anywhere**:
the pipeline signs in with a short-lived OIDC token that GitHub issues per run, and the cloud only accepts
tokens from this repository (`acme/notes`) and, for deployments, from a named GitHub environment.

## What you get

| Piece | Where | Does |
|---|---|---|
| CI | `.github/workflows/ci.yml` | lint, tests against PostgreSQL, `alembic check`, image build, vulnerability scan (fails on a fixable HIGH or CRITICAL), SBOM, `terraform fmt` and `validate` |
| CD | `.github/workflows/deploy.yml` | push to `main` deploys **dev**; "Run workflow" promotes a tag to any environment: build once, push, sign, migrate, deploy, smoke test |
| Stack | `deploy/azure/` | private network, private database, secret manager, service, load balancing |
| One-time setup | `deploy/azure/bootstrap/` | state storage, image registry, the OIDC trust (run by an administrator, once) |
| Capacity | `deploy/azure/environments/*.tfvars` | numbers per environment: instances, CPU, memory, database size |

Runs on **Azure Container Apps** with a managed HTTPS address, **PostgreSQL Flexible Server** on a private
network, secrets in **Key Vault**, images in **Container Registry**. There is no web application firewall in
this bundle (Front Door adds one).

## One-time setup (about 20 minutes)

1. **Create the identities and storage.** In `deploy/azure/bootstrap/`, sign in with your own
   account (`az login`; you need rights to create applications in Entra ID and to assign roles) and run
   `terraform init && terraform apply -var subscription_id=<id>`. It creates a state storage account (no account
   keys), a container registry, and one Entra application per environment with a federated credential.
   Keep the `terraform.tfstate` it leaves in that folder somewhere safe: it is the only record of these.
2. **Create the GitHub environments** (Settings > Environments): `dev`, `staging`, `prod`.
   On the production environment add **required reviewers** (and restrict it to the `main` branch). The trust
   in step 1 is per environment, so nobody can deploy to production without passing through it.
3. **Set the variables** of each GitHub environment (not secrets: none of these is secret) from the
   bootstrap's outputs:

   | Variable | Value |
   |---|---|
   | `AZURE_CLIENT_ID` | the application for this environment (`deploy_client_ids`) |
   | `AZURE_TENANT_ID` | `tenant_id` |
   | `AZURE_SUBSCRIPTION_ID` | your subscription id |
   | `ACR_NAME` | `registry_name` |
   | `TF_STATE_RESOURCE_GROUP` | `state_resource_group` |
   | `TF_STATE_STORAGE_ACCOUNT` | `state_storage_account` |
4. **Fill the secrets.** The first pipeline run creates the secret containers and the DATABASE_URL secret by itself and
   stops where it needs a person. These hold values only you should know; set them in the cloud's secret manager
   (never in the repository, never in a tfvars file):

   * `AUTH_JWT_SECRET`
   ```bash
   az keyvault secret set --vault-name <vault from the first run> --name <NAME-with-dashes> --value '<value>'
   ```

## Every deployment, step by step

1. **Build once** from the commit, push the image tagged with the commit SHA (tags are immutable), sign it with
   cosign (keyless: the signature names this workflow) and record provenance and an SBOM with it.
2. **Infrastructure**: `terraform apply` with the image the service already runs, so the infrastructure is current
   but the service does not move yet. (The first deployment has no image yet and starts from the new one.)
3. **Migrations**: the *new* image runs `alembic upgrade head` once as a separate task. If it fails the pipeline
   stops and the running service is untouched. Several instances never migrate at the same time because the
   server image does not migrate on start-up here. **Write migrations so the previous version still works**
   against the new schema (add a column first, stop using the old one in a later release, drop it after that).
4. **Roll out** the new image.
   In single-revision mode the previous revision keeps serving until the new one passes its probes.
5. **Smoke test**: `GET /ready` (which also queries the database) on the public address, retried for a minute.

### Promote to staging or production

Actions > Deploy > Run workflow, pick the environment and paste the image tag (the commit SHA) that is already
running in dev. The image is **not rebuilt**: what you tested is what ships. Production waits for its reviewers.

### Roll back

Run the workflow again with the tag of the last good version. A migration that already ran is not undone;
this is why migrations must stay backward compatible. Restoring the database from a backup is a separate,
deliberate act (see the cloud's console); backups are on in every environment, and kept longer where
`deletion_protection = true`.

## Capacity and cost

Open `deploy/azure/environments/<env>.tfvars` and change the numbers: `min_instances`, `max_instances`,
`cpu`, `memory`, `db_class`, `db_storage_gb`, `db_high_availability`. No code changes, no rebuild. The valid
CPU and memory pairs are limited by the platform; Terraform tells you if a pair is not offered.

* **dev** (profile small): 1 to 2 instances of 500m CPU and 1024 MB; database `B_Standard_B1ms` with 20 GB.

* **staging** (profile small): 1 to 2 instances of 500m CPU and 1024 MB; database `B_Standard_B1ms` with 20 GB.

* **prod** (profile medium): 2 to 8 instances of 1000m CPU and 2048 MB; database `GP_Standard_D2ds_v5` with 50 GB, standby in a second zone, deletion protected.

Each instance opens a few database connections (`DB_POOL_SIZE` plus `DB_MAX_OVERFLOW`, 10 by default). Keep
`max_instances` times that below the database's connection limit, or raise the database size.

## Security notes

* Database: private network only, encrypted at rest, TLS required, backups on.
* The service's own identity can read its own secrets and nothing else.
* The deploy identity is powerful inside its account (it creates networks, databases and roles). Use a
  **separate account / project / subscription per environment** for production, and read
  `bootstrap/` before applying it.
* The generated password of the database lives in the Terraform **state** as well as in the secret manager.
  The state storage is created private and versioned: limit who can read it.
* Verify a signed image: `cosign verify --certificate-identity-regexp 'https://github.com/acme/notes/' --certificate-oidc-issuer https://token.actions.githubusercontent.com <image>@<digest>`.
* GitHub Actions in the workflows are pinned to commit SHAs (the tag is in a comment); let Dependabot or
  Renovate propose updates.

## Limits (known)

* Not included: the payments worker, file storage with malware scanning, Redis, or a Keycloak server of its
  own. A spec that uses them cannot enable deployment yet.
* Custom domains and DNS are yours to add.
* `terraform apply` has been validated (`terraform validate`) but **not run against a real account** by the
  builder: do the first deployment in a throwaway account or the dev environment.
* GitHub Actions only (no GitLab CI or Bitbucket Pipelines yet).
