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

  # env name -> Key Vault secret
  secret_refs = merge(
    { DATABASE_URL = azurerm_key_vault_secret.database_url.versionless_id },
    { for name, s in azurerm_key_vault_secret.app : name => s.versionless_id },
  )
  cpu_cores    = var.cpu / 1000
  memory_limit = "${var.memory / 1024}Gi"
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = local.name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "main" {
  name                       = local.name
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  infrastructure_subnet_id   = azurerm_subnet.apps.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

resource "azurerm_container_app" "app" {
  name                         = "app"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = local.secret_refs
    content {
      name                = lower(replace(secret.key, "_", "-"))
      key_vault_secret_id = secret.value
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  ingress {
    external_enabled           = true
    target_port                = 8000
    transport                  = "auto"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_instances
    max_replicas = var.max_instances

    http_scale_rule {
      name                = "concurrency"
      concurrent_requests = "50"
    }

    container {
      name    = "app"
      image   = var.image
      cpu     = local.cpu_cores
      memory  = local.memory_limit
      command = local.serve_command

      dynamic "env" {
        for_each = local.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_refs
        content {
          name        = env.key
          secret_name = lower(replace(env.key, "_", "-"))
        }
      }

      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        interval_seconds        = 5
        failure_count_threshold = 12
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.app_secrets,
    azurerm_role_assignment.app_pull,
    azurerm_postgresql_flexible_server_database.app,
  ]
}

# Same image and settings, different command: applies the database migrations once. The pipeline starts
# it (az containerapp job start) and waits before the app is updated.
resource "azurerm_container_app_job" "migrate" {
  name                         = "migrate"
  location                     = azurerm_resource_group.main.location
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = local.secret_refs
    content {
      name                = lower(replace(secret.key, "_", "-"))
      key_vault_secret_id = secret.value
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  template {
    container {
      name    = "migrate"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["alembic", "upgrade", "head"]

      dynamic "env" {
        for_each = local.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_refs
        content {
          name        = env.key
          secret_name = lower(replace(env.key, "_", "-"))
        }
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.app_secrets,
    azurerm_role_assignment.app_pull,
  ]
}
