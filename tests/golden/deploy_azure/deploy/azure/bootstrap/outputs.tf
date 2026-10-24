output "tenant_id" {
  value = data.azurerm_client_config.current.tenant_id
}

output "state_resource_group" {
  value = azurerm_resource_group.shared.name
}

output "state_storage_account" {
  value = azurerm_storage_account.state.name
}

output "registry_name" {
  value = azurerm_container_registry.main.name
}

output "registry_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "deploy_client_ids" {
  description = "Set each as the AZURE_CLIENT_ID variable of the matching GitHub environment."
  value       = { for env, app in azuread_application.deploy : env => app.client_id }
}
