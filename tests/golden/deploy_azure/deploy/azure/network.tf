locals {
  name = "${var.project}-${var.environment}"
  # Names that must be short and alphanumeric are derived without dashes.
  short = substr(replace("${var.project}${var.environment}", "-", ""), 0, 18)
}

resource "azurerm_resource_group" "main" {
  name     = "${local.name}-rg"
  location = var.region
}

resource "azurerm_management_lock" "main" {
  count      = var.deletion_protection ? 1 : 0
  name       = "protect-${local.name}"
  scope      = azurerm_resource_group.main.id
  lock_level = "CanNotDelete"
  notes      = "deletion_protection = true in environments/${var.environment}.tfvars"
}

resource "azurerm_virtual_network" "main" {
  name                = local.name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = [var.vnet_cidr]
}

# The Container Apps environment lives here (outbound and private traffic).
resource "azurerm_subnet" "apps" {
  name                 = "apps"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 7, 0)]

  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# The database lives here and has no public address.
resource "azurerm_subnet" "db" {
  name                 = "db"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 8, 10)]

  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_private_dns_zone" "db" {
  name                = "${local.short}.private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "db" {
  name                = "${local.name}-db"
  private_dns_zone_id = azurerm_private_dns_zone.db.id
  virtual_network_id  = azurerm_virtual_network.main.id
}
