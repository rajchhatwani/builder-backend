locals {
  serve_command = ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers $${UVICORN_WORKERS:-1}"]

  base_env = {
    APP_ENV         = var.app_env
    LOG_LEVEL       = "INFO"
    UVICORN_WORKERS = "1"
    DB_POOL_SIZE    = "5"
    DB_MAX_OVERFLOW = "5"
  }
  env_vars = merge(local.base_env, var.app_env_vars)

  secret_env = merge(
    { DATABASE_URL = google_secret_manager_secret.database_url.secret_id },
    { for name, s in google_secret_manager_secret.app : name => s.secret_id },
  )
  cpu_limit    = tostring(var.cpu / 1000)
  memory_limit = "${var.memory}Mi"
}

# The identity of the running service: it can read its own secrets and nothing else.
resource "google_service_account" "app" {
  account_id   = substr(local.name, 0, 30)
  display_name = "${local.name} service"
}

resource "google_cloud_run_v2_service" "app" {
  name                = local.name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.deletion_protection

  template {
    service_account = google_service_account.app.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.main.id
        subnetwork = google_compute_subnetwork.main.id
      }
    }

    containers {
      image   = var.image
      command = local.serve_command

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = local.cpu_limit
          memory = local.memory_limit
        }
      }

      dynamic "env" {
        for_each = local.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 12
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds = 30
      }
    }
  }

  # A new revision receives traffic only after its startup probe passes; if it never does, the
  # deployment fails and the previous revision keeps serving.
  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_secret_manager_secret_iam_member.database_url,
    google_secret_manager_secret_iam_member.app,
    google_secret_manager_secret_version.database_url,
    google_sql_database.app,
    google_sql_user.app,
  ]
}

# A public API: anyone may call it. Sign-in and authorization are the application's job. To make it
# private instead, remove this binding and put API Gateway or an identity-aware proxy in front.
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.app.name
  location = google_cloud_run_v2_service.app.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Same image and settings, different command: applies the database migrations once. The pipeline runs it
# (gcloud run jobs execute --wait) before the service is updated.
resource "google_cloud_run_v2_job" "migrate" {
  name                = "${local.name}-migrate"
  location            = var.region
  deletion_protection = var.deletion_protection

  template {
    template {
      service_account = google_service_account.app.email
      max_retries     = 0
      timeout         = "600s"

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = google_compute_network.main.id
          subnetwork = google_compute_subnetwork.main.id
        }
      }

      containers {
        image   = var.image
        command = ["alembic", "upgrade", "head"]

        dynamic "env" {
          for_each = local.env_vars
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = local.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }
      }
    }
  }
}
