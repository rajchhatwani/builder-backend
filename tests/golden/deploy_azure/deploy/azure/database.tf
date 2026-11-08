# PostgreSQL on a private network. The password is generated here and stored in Key Vault as part of
# DATABASE_URL; it also lives in the Terraform state, so protect the state account (bootstrap/ creates
# it private, versioned and without shared keys) and limit who can read it.
resource "random_password" "db" {
  length  = 32
  special = false # letters and digits only: safe inside a connection URL
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                = local.name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  version             = "16"
  sku_name            = var.db_class
  storage_mb          = var.db_storage_gb * 1024

  delegated_subnet_id           = azurerm_subnet.db.id
  private_dns_zone_id           = azurerm_private_dns_zone.db.id
  public_network_access_enabled = false

  administrator_login    = "app"
  administrator_password = random_password.db.result

  backup_retention_days        = var.deletion_protection ? 14 : 7
  geo_redundant_backup_enabled = false
  zone                         = "1"

  dynamic "high_availability" {
    for_each = var.db_high_availability ? [1] : []
    content {
      mode                      = "ZoneRedundant"
      standby_availability_zone = "2"
    }
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.db]
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = "app"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
