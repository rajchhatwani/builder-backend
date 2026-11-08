terraform {
  required_version = ">= 1.10"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State in a Cloud Storage bucket created by bootstrap/ (locking is built in). Pass at init time:
  #   terraform init -backend-config="bucket=..." -backend-config="prefix=deploy-gcp/<env>"
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
