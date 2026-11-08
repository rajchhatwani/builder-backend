locals {
  # Secrets the application reads from its environment. Terraform creates the empty containers; YOU
  # set their values (never in this repository or in a .tfvars file):
  #   printf '%s' 'value' | gcloud secrets versions add deploy-gcp-<environment>-<NAME> --data-file=-
  app_secret_names = ["AUTH_JWT_SECRET"]
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "${local.name}-DATABASE_URL"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  # ssl=require: the database accepts encrypted connections only.
  secret_data_wo         = "postgresql+asyncpg://app:${random_password.db.result}@${google_sql_database_instance.main.private_ip_address}:5432/app?ssl=require"
  secret_data_wo_version = 1
}

resource "google_secret_manager_secret" "app" {
  for_each  = toset(local.app_secret_names)
  secret_id = "${local.name}-${each.value}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# Only the service's own identity may read these secrets.
resource "google_secret_manager_secret_iam_member" "database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "app" {
  for_each  = google_secret_manager_secret.app
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}
