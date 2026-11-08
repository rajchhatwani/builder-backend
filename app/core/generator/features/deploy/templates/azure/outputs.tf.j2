output "url" {
  description = "Where the service answers (HTTPS, with a certificate managed by Azure)."
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "app_name" {
  value = azurerm_container_app.app.name
}

output "migrate_job" {
  description = "Run once per deployment with the pipeline (see .github/workflows/deploy.yml)."
  value       = azurerm_container_app_job.migrate.name
}

output "key_vault" {
  value = azurerm_key_vault.main.name
}

output "secrets_to_fill" {
  description = "Key Vault secrets whose values you must set before the first deployment."
  value       = [for s in azurerm_key_vault_secret.app : s.name]
}

output "deployed_image" {
  description = "The image the service runs now. The pipeline starts from it, so a first step can update the infrastructure without touching the service."
  value       = azurerm_container_app.app.template[0].container[0].image
}
