# Run ONCE per Azure subscription by an administrator, with your own credentials (az login). It creates
# what the pipeline needs before it can run: the Terraform state storage, the container registry, and
# one Microsoft Entra identity per environment that this repository's GitHub Actions workflows can use
# through federated credentials (no client secret exists). Its own state stays local (terraform.tfstate
# here): keep that file safe.
terraform {
  required_version = ">= 1.10"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

provider "azuread" {}
