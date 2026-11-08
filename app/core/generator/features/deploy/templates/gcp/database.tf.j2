# PostgreSQL with a private IP only. The password is generated here and stored in Secret Manager as part
# of DATABASE_URL; it also lives in the Terraform state, so protect the state bucket (bootstrap/ creates
# it private and versioned) and limit who can read it.
resource "random_password" "db" {
  length  = 32
  special = false # letters and digits only: safe inside a connection URL
}

resource "google_sql_database_instance" "main" {
  name                = local.name
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.deletion_protection

  settings {
    tier                        = var.db_class
    edition                     = "ENTERPRISE"
    availability_type           = var.db_high_availability ? "REGIONAL" : "ZONAL"
    disk_size                   = var.db_storage_gb
    disk_autoresize             = true
    disk_type                   = "PD_SSD"
    deletion_protection_enabled = var.deletion_protection

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = var.deletion_protection
      backup_retention_settings {
        retained_backups = var.deletion_protection ? 14 : 3
      }
    }

    maintenance_window {
      day  = 7
      hour = 3
    }
  }

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_sql_database" "app" {
  name     = "app"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "app" {
  name     = "app"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}
