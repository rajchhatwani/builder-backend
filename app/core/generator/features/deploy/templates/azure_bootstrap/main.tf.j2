data "azurerm_client_config" "current" {}

locals {
  short = substr(replace(var.project, "-", ""), 0, 12)
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "shared" {
  name     = "${var.project}-shared-rg"
  location = var.region
}

# --- Terraform state: private, versioned, Entra ID access only (no account keys) ------------------

resource "azurerm_storage_account" "state" {
  name                            = "${local.short}tf${random_string.suffix.result}"
  resource_group_name             = azurerm_resource_group.shared.name
  location                        = azurerm_resource_group.shared.location
  account_tier                    = "Standard"
  account_replication_type        = "GRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false

  blob_properties {
    versioning_enabled = true
  }
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

# --- Image registry: no admin user; the service pulls with its own identity -----------------------

resource "azurerm_container_registry" "main" {
  name                = "${local.short}${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.shared.name
  location            = azurerm_resource_group.shared.location
  sku                 = "Standard"
  admin_enabled       = false
}

# --- GitHub OIDC: one Entra application per environment, trusted for exactly one GitHub environment

resource "azuread_application" "deploy" {
  for_each     = toset(var.environments)
  display_name = "${var.project}-deploy-${each.value}"
}

resource "azuread_service_principal" "deploy" {
  for_each  = toset(var.environments)
  client_id = azuread_application.deploy[each.value].client_id
}

# Only jobs of THIS repository that run in THIS GitHub environment (where approvals live) can sign in.
resource "azuread_application_federated_identity_credential" "github" {
  for_each       = toset(var.environments)
  application_id = azuread_application.deploy[each.value].id
  display_name   = "github-${each.value}"
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repo}:environment:${each.value}"
  audiences      = ["api://AzureADTokenExchange"]
}

# What `terraform apply` of ../ needs: create resource groups and everything in them, and grant the
# service its roles. Contributor at subscription level is broad: use a separate subscription per
# environment for production, and review these assignments before the first apply.
resource "azurerm_role_assignment" "contributor" {
  for_each             = toset(var.environments)
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.deploy[each.value].object_id
}

resource "azurerm_role_assignment" "rbac_admin" {
  for_each             = toset(var.environments)
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azuread_service_principal.deploy[each.value].object_id
}

resource "azurerm_role_assignment" "state" {
  for_each             = toset(var.environments)
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_service_principal.deploy[each.value].object_id
}

resource "azurerm_role_assignment" "push" {
  for_each             = toset(var.environments)
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azuread_service_principal.deploy[each.value].object_id
}
