resource "google_project_service" "apis" {
  for_each = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Terraform state: private, versioned; Cloud Storage provides the locking ----------------------

resource "google_storage_bucket" "state" {
  name                        = "${var.project}-tfstate-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.apis]
}

# --- Image registry: tags cannot be overwritten ---------------------------------------------------

resource "google_artifact_registry_repository" "app" {
  repository_id = var.project
  location      = var.region
  format        = "DOCKER"

  docker_config {
    immutable_tags = true
  }

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 50
    }
  }

  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "7776000s" # 90 days
    }
  }

  depends_on = [google_project_service.apis]
}

# --- Workload Identity Federation: the workflow proves who it is with a short-lived token --------

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${var.project}-github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.repo_env"   = "assertion.repository + '/' + assertion.environment"
  }

  # Refuse tokens from any other repository before anything else is checked.
  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deploy" {
  for_each     = toset(var.environments)
  account_id   = substr("${var.project}-deploy-${each.value}", 0, 30)
  display_name = "Deploys ${each.value}"
}

# Only jobs of THIS repository that run in THIS GitHub environment (where approvals live) may act as it.
resource "google_service_account_iam_member" "github" {
  for_each           = toset(var.environments)
  service_account_id = google_service_account.deploy[each.value].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repo_env/${var.github_repo}/${each.value}"
}

# What `terraform apply` of ../ needs. Network, database and service roles cannot be limited to a name
# prefix, so these identities are powerful inside the project: use a separate Google Cloud project per
# environment for production, and review this list before the first apply.
locals {
  deploy_roles = [
    "roles/run.admin",
    "roles/cloudsql.admin",
    "roles/secretmanager.admin",
    "roles/compute.networkAdmin",
    "roles/servicenetworking.networksAdmin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.serviceAccountUser",
    "roles/serviceusage.serviceUsageAdmin",
  ]
  grants = {
    for pair in setproduct(var.environments, local.deploy_roles) :
    "${pair[0]}/${pair[1]}" => { env = pair[0], role = pair[1] }
  }
}

resource "google_project_iam_member" "deploy" {
  for_each = local.grants
  project  = var.project_id
  role     = each.value.role
  member   = "serviceAccount:${google_service_account.deploy[each.value.env].email}"
}

resource "google_artifact_registry_repository_iam_member" "push" {
  for_each   = toset(var.environments)
  repository = google_artifact_registry_repository.app.name
  location   = google_artifact_registry_repository.app.location
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deploy[each.value].email}"
}

resource "google_storage_bucket_iam_member" "state" {
  for_each = toset(var.environments)
  bucket   = google_storage_bucket.state.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${google_service_account.deploy[each.value].email}"
}
